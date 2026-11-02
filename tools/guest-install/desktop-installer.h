/* Authenticated, bounded app-bundle transfer. No tar, shell, or arbitrary paths.
 * Included by iossweet-agent.m. Only this development VM's managed apps change.
 */
#include <CommonCrypto/CommonDigest.h>
#include <fcntl.h>
#include <sys/statvfs.h>

static NSString *const RegistryPath=@"/private/var/iossweet/apps.plist";
static NSDictionary *selectedApp;

static BOOL validBundleId(NSString *s) {
    if(![s isKindOfClass:NSString.class] || s.length<3 || s.length>180 ||
       [s.lowercaseString hasPrefix:@"com.apple."] || [s hasPrefix:@"."] ||
       [s hasSuffix:@"."] || [s containsString:@".."] || ![s containsString:@"."])return NO;
    return [s rangeOfCharacterFromSet:[[NSCharacterSet characterSetWithCharactersInString:
        @"abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-"] invertedSet]].location==NSNotFound;
}

static NSMutableDictionary *managedApps(void) {
    NSMutableDictionary *r=[[NSDictionary dictionaryWithContentsOfFile:RegistryPath] mutableCopy];
    if(!r)r=[NSMutableDictionary dictionary];
    NSString *bid=configuration[@"BundleId"],*path=configuration[@"BundlePath"];
    if(validBundleId(bid) && path && !r[bid] &&
       [[NSFileManager defaultManager] fileExistsAtPath:[path stringByAppendingPathComponent:@"Info.plist"]])
        r[bid]=@{@"BundleId":bid,@"BundlePath":path};
    return r;
}

static NSDictionary *selectApp(NSString *bid) {
    if(!validBundleId(bid))return nil;
    NSDictionary *app=managedApps()[bid];
    NSString *path=app[@"BundlePath"];
    NSString *expected=[NSString stringWithFormat:@"/Applications/IOSSweet-%@.app",bid];
    BOOL legacy=[bid isEqual:configuration[@"BundleId"]] && [path isEqual:configuration[@"BundlePath"]];
    return [path isEqual:expected] || legacy ? app : nil;
}

static BOOL readExact(int fd,void *target,size_t size) {
    char *p=target;
    while(size){ssize_t got=recv(fd,p,size,0);if(got<=0)return NO;p+=got;size-=(size_t)got;}
    return YES;
}

static BOOL safeRelative(NSString *path) {
    if(![path isKindOfClass:NSString.class] || !path.length || path.length>1024 ||
       [path hasPrefix:@"/"] || [path containsString:@"\\"] || [path containsString:@":"] ||
       [path rangeOfString:[NSString stringWithFormat:@"%C",(unichar)0]].location!=NSNotFound)return NO;
    for(NSString *part in [path componentsSeparatedByString:@"/"])
        if(!part.length || [part isEqual:@"."] || [part isEqual:@".."])return NO;
    return YES;
}

static NSDictionary *receiveApp(int fd,unsigned long long contentLength) {
    const unsigned long long maximum=4ULL*1024*1024*1024;
    if(contentLength<8 || contentLength>maximum)return @{@"error":@"Bundle transfer must be between 8 bytes and 4 GiB"};
    uint32_t be=0;if(!readExact(fd,&be,4))return @{@"error":@"Truncated transfer"};
    uint32_t length=ntohl(be);
    if(length<2 || length>8*1024*1024 || length+4ULL>contentLength)return @{@"error":@"Invalid transfer manifest length"};
    NSMutableData *manifest=[NSMutableData dataWithLength:length];
    if(!readExact(fd,manifest.mutableBytes,length))return @{@"error":@"Truncated manifest"};
    NSDictionary *m=[NSJSONSerialization JSONObjectWithData:manifest options:0 error:nil];
    if(![m isKindOfClass:NSDictionary.class] || ![m[@"version"] isEqual:@1] || !validBundleId(m[@"bundleId"]))
        return @{@"error":@"Invalid bundle manifest"};
    NSArray *files=m[@"files"];
    if(![files isKindOfClass:NSArray.class] || files.count<2 || files.count>50000)return @{@"error":@"Invalid file count"};
    unsigned long long total=4ULL+length;
    NSMutableSet *seen=[NSMutableSet set];
    for(NSDictionary *f in files){
        if(![f isKindOfClass:NSDictionary.class] || !safeRelative(f[@"path"]) ||
           ![f[@"size"] isKindOfClass:NSNumber.class] || [f[@"size"] longLongValue]<0 ||
           ![f[@"sha256"] isKindOfClass:NSString.class] || [f[@"sha256"] length]!=64 ||
           !([f[@"mode"] isEqual:@420] || [f[@"mode"] isEqual:@493]))return @{@"error":@"Invalid file metadata"};
        NSString *key=[f[@"path"] lowercaseString];
        if([seen containsObject:key])return @{@"error":@"Duplicate bundle path"};
        [seen addObject:key];
        unsigned long long size=[f[@"size"] unsignedLongLongValue];
        if(size>maximum || total>maximum-size)return @{@"error":@"Bundle too large"};
        total+=size;
    }
    if(total!=contentLength || ![seen containsObject:@"info.plist"])return @{@"error":@"Manifest size or Info.plist mismatch"};
    struct statvfs space={0};
    if(statvfs("/Applications",&space)!=0 || (unsigned long long)space.f_bavail*space.f_frsize<total+64ULL*1024*1024)
        return @{@"error":@"Not enough free space in the iOS guest"};
    NSFileManager *fm=NSFileManager.defaultManager;
    NSString *target=[NSString stringWithFormat:@"/Applications/IOSSweet-%@.app",m[@"bundleId"]];
    // Updating a live executable is unsafe; refuse instead of killing it implicitly.
    int (*listpids)(void*,int)=dlsym(RTLD_DEFAULT,"proc_listallpids");
    int (*pidpath)(int,void*,uint32_t)=dlsym(RTLD_DEFAULT,"proc_pidpath");
    if(!listpids||!pidpath)return @{@"error":@"Cannot verify app process state"};
    int pids[8192];int count=listpids(pids,sizeof(pids));
    if(count<0 || count>=8192)return @{@"error":@"Process table unavailable or truncated"};
    NSString *prefix=[target stringByAppendingString:@"/"];
    for(int i=0;i<count;i++){char p[4096]={0};if(pidpath(pids[i],p,sizeof(p))>0 && [[NSString stringWithUTF8String:p] hasPrefix:prefix])
        return @{@"error":@"App is running. Stop it in the library before updating."};}
    NSString *stage=[@"/private/var/iossweet/staging" stringByAppendingPathComponent:NSUUID.UUID.UUIDString];
    NSString *backup=[stage stringByAppendingString:@"-previous"];
    NSError *error=nil;BOOL committed=NO,hadOld=NO;
    @try {
        atomic_store(&operationPhase,"receiving_and_verifying_bundle");
        if(![fm createDirectoryAtPath:stage withIntermediateDirectories:YES attributes:@{NSFilePosixPermissions:@493} error:&error])
            return @{@"error":error.localizedDescription ?: @"Cannot create staging directory"};
        for(NSDictionary *f in files){@autoreleasepool{
            NSString *p=[stage stringByAppendingPathComponent:f[@"path"]];
            if(![fm createDirectoryAtPath:p.stringByDeletingLastPathComponent withIntermediateDirectories:YES attributes:@{NSFilePosixPermissions:@493} error:&error])
                return @{@"error":@"Conflicting file and directory paths"};
            int out=open(p.fileSystemRepresentation,O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW,0600);
            if(out<0)return @{@"error":@"Cannot create staged file"};
            CC_SHA256_CTX ctx;CC_SHA256_Init(&ctx);char buffer[65536];unsigned long long left=[f[@"size"] unsignedLongLongValue];BOOL ok=YES;
            while(left){size_t n=(size_t)MIN(left,sizeof(buffer));if(!readExact(fd,buffer,n)){ok=NO;break;}
                CC_SHA256_Update(&ctx,buffer,(CC_LONG)n);size_t at=0;
                while(at<n){ssize_t w=write(out,buffer+at,n-at);if(w<=0){ok=NO;break;}at+=(size_t)w;}
                if(!ok)break;left-=n;}
            if(ok && fchmod(out,[f[@"mode"] intValue])!=0)ok=NO;
            if(ok && fsync(out)!=0)ok=NO;close(out);
            unsigned char digest[CC_SHA256_DIGEST_LENGTH];CC_SHA256_Final(digest,&ctx);
            NSMutableString *hex=[NSMutableString string];for(int i=0;i<CC_SHA256_DIGEST_LENGTH;i++)[hex appendFormat:@"%02x",digest[i]];
            if(!ok || ![hex isEqual:f[@"sha256"]])return @{@"error":@"File transfer interrupted or SHA-256 mismatch"};
        }}
        NSData *bytes=[NSData dataWithContentsOfFile:[stage stringByAppendingPathComponent:@"Info.plist"]];
        id info=bytes?[NSPropertyListSerialization propertyListWithData:bytes options:0 format:NULL error:nil]:nil;
        if(![info isKindOfClass:NSDictionary.class] || ![info[@"CFBundleIdentifier"] isEqual:m[@"bundleId"]])
            return @{@"error":@"Bundle ID does not match its manifest"};
        NSString *exe=info[@"CFBundleExecutable"];
        if(!safeRelative(exe) || [exe containsString:@"/"] || ![fm isExecutableFileAtPath:[stage stringByAppendingPathComponent:exe]])
            return @{@"error":@"Bundle executable missing"};
        atomic_store(&operationPhase,"committing_bundle");
        if([fm fileExistsAtPath:target]){if(![fm moveItemAtPath:target toPath:backup error:&error])return @{@"error":@"Cannot back up previous bundle"};hadOld=YES;}
        if(![fm moveItemAtPath:stage toPath:target error:&error]){
            if(hadOld)[fm moveItemAtPath:backup toPath:target error:nil];
            return @{@"error":@"Cannot commit installed bundle"};
        }
        NSMutableDictionary *registry=managedApps();
        NSDictionary *entry=@{@"BundleId":m[@"bundleId"],@"BundlePath":target,
            @"DisplayName":info[@"CFBundleDisplayName"] ?: info[@"CFBundleName"] ?: m[@"bundleId"]};
        registry[m[@"bundleId"]]=entry;
        if(![registry writeToFile:RegistryPath atomically:YES]){
            [fm removeItemAtPath:target error:nil];if(hadOld)[fm moveItemAtPath:backup toPath:target error:nil];
            return @{@"error":@"Cannot persist app library; bundle rolled back"};
        }
        chmod(RegistryPath.fileSystemRepresentation,0600);committed=YES;selectedApp=entry;
        if(hadOld)[fm removeItemAtPath:backup error:nil];
        return @{@"transferred":@YES,@"bundleId":m[@"bundleId"],@"path":target};
    } @finally {if(!committed)[fm removeItemAtPath:stage error:nil];}
}

static NSDictionary *stopSelectedApp(void) {
    int (*listpids)(void*,int)=dlsym(RTLD_DEFAULT,"proc_listallpids");
    int (*pidpath)(int,void*,uint32_t)=dlsym(RTLD_DEFAULT,"proc_pidpath");
    if(!listpids||!pidpath)return @{@"error":@"Process inspection unavailable"};
    int pids[8192],count=listpids(pids,sizeof(pids)),stopped=0;
    if(count<0||count>=8192)return @{@"error":@"Cannot verify process table"};
    NSString *prefix=[selectedApp[@"BundlePath"] stringByAppendingString:@"/"];
    for(int i=0;i<count;i++){char path[4096]={0};if(pids[i]>1 && pidpath(pids[i],path,sizeof(path))>0 &&
        [[NSString stringWithUTF8String:path] hasPrefix:prefix]){if(kill(pids[i],SIGTERM)==0)stopped++;}}
    return @{@"stopRequested":@YES,@"count":@(stopped)};
}
