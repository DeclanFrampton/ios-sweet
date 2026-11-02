/* iOS Sweet local development bridge. Install ONLY on a disposable QEMU clone.
 * No shell commands, Apple credentials, public listener or identity spoofing.
 * Authorizes one pre-staged bundle through a root-owned allowlist.
 */
#import <Foundation/Foundation.h>
#import <CoreFoundation/CoreFoundation.h>
#import <objc/message.h>
#import <objc/runtime.h>
#include <arpa/inet.h>
#include <dlfcn.h>
#include <errno.h>
#include <netinet/in.h>
#include <mach/mach.h>
#include <mach/arm/thread_status.h>
#include <dispatch/dispatch.h>
#include <pthread.h>
#include <signal.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>

static NSString *const ConfigPath = @"/private/var/iossweet/bridge.plist";
static NSDictionary *configuration;
static NSDictionary *effectivePrivileges;
static NSString *guestUDID;
static NSString *identityState = @"not_queried";
static pthread_mutex_t identityMutex = PTHREAD_MUTEX_INITIALIZER;
static pthread_mutex_t operationsMutex = PTHREAD_MUTEX_INITIALIZER;
static unsigned activeConnections;
static pthread_mutex_t connectionMutex = PTHREAD_MUTEX_INITIALIZER;
static _Atomic(const char *) operationPhase="idle";
static _Atomic(mach_port_t) operationThread=MACH_PORT_NULL;
// Apple's XNU memorystatus interface. This changes ONLY this test helper's
// own bounded process limit; it never disables jetsam or edits global policy.
typedef struct { int32_t active; uint32_t activeAttr; int32_t inactive; uint32_t inactiveAttr; } AgentMemlimit;
static AgentMemlimit initialLimit, currentLimit;
static int limitReadResult=-1, limitSetResult=-1, limitErrno=0;
static void configureOwnMemoryLimit(void) {
    int (*control)(uint32_t,int32_t,uint32_t,void*,size_t)=dlsym(RTLD_DEFAULT,"memorystatus_control");
    if(!control)return;
    limitReadResult=control(8,getpid(),0,&initialLimit,sizeof(initialLimit));
    AgentMemlimit bounded={256,1,256,1};
    limitSetResult=control(7,getpid(),0,&bounded,sizeof(bounded));limitErrno=limitSetResult==0?0:errno;
    control(8,getpid(),0,&currentLimit,sizeof(currentLimit));
}

static NSDictionary *processMemory(void) {
    task_vm_info_data_t info={0};mach_msg_type_number_t count=TASK_VM_INFO_COUNT;
    kern_return_t rc=task_info(mach_task_self(),TASK_VM_INFO,(task_info_t)&info,&count);
    return @{@"initialActiveMiB":@(initialLimit.active),@"initialInactiveMiB":@(initialLimit.inactive),
             @"currentActiveMiB":@(currentLimit.active),@"currentInactiveMiB":@(currentLimit.inactive),
             @"readResult":@(limitReadResult),@"setResult":@(limitSetResult),@"setErrno":@(limitErrno),
             @"footprintBytes":@(rc==KERN_SUCCESS?info.phys_footprint:0),
             @"appliesOnlyToAgent":@YES};
}

static void *queryIdentity(void *unused) {
    (void)unused;
    @autoreleasepool {
        pthread_mutex_lock(&identityMutex);
        identityState = @"querying_MobileGestalt";
        pthread_mutex_unlock(&identityMutex);
        void *library = dlopen("/usr/lib/libMobileGestalt.dylib", RTLD_LAZY);
        CFTypeRef (*copyAnswer)(CFStringRef) = library ? dlsym(library, "MGCopyAnswer") : NULL;
        CFTypeRef answer = copyAnswer ? copyAnswer(CFSTR("UniqueDeviceID")) : NULL;
        pthread_mutex_lock(&identityMutex);
        if (answer && CFGetTypeID(answer) == CFStringGetTypeID()) {
            NSString *s = (__bridge NSString *)answer;
            BOOL placeholder=YES;
            for(NSUInteger i=1;i<s.length;i++)if([s characterAtIndex:i]!=[s characterAtIndex:0]){placeholder=NO;break;}
            if (s.length >= 16 && s.length <= 80 && !placeholder) guestUDID = [s copy];
            if(placeholder)identityState=@"placeholder_from_MobileGestalt_not_a_real_UDID";
        }
        if(![identityState hasPrefix:@"placeholder_"])identityState = guestUDID ? @"reported_by_MobileGestalt" : @"not_provided_by_guest";
        pthread_mutex_unlock(&identityMutex);
        if (answer) CFRelease(answer);
    }
    return NULL;
}

static id workspace(void) {
    dlopen("/System/Library/Frameworks/MobileCoreServices.framework/MobileCoreServices", RTLD_LAZY);
    dlopen("/System/Library/Frameworks/CoreServices.framework/CoreServices", RTLD_LAZY);
    Class c = NSClassFromString(@"LSApplicationWorkspace");
    SEL selector = NSSelectorFromString(@"defaultWorkspace");
    return c && [c respondsToSelector:selector] ? ((id (*)(id,SEL))objc_msgSend)(c,selector) : nil;
}

static NSDictionary *agentPrivileges(void) {
    void *security=dlopen("/System/Library/Frameworks/Security.framework/Security",RTLD_LAZY);
    CFTypeRef (*create)(CFAllocatorRef)=security?dlsym(security,"SecTaskCreateFromSelf"):NULL;
    CFTypeRef (*copy)(CFTypeRef,CFStringRef,CFErrorRef*)=security?dlsym(security,"SecTaskCopyValueForEntitlement"):NULL;
    if(!create||!copy)return @{@"queryAvailable":@NO};
    CFTypeRef task=create(kCFAllocatorDefault);if(!task)return @{@"queryAvailable":@NO};
    NSMutableDictionary *result=[@{@"queryAvailable":@YES} mutableCopy];
    NSArray *keys=@[@"com.apple.private.MobileContainerManager.allowed",@"com.apple.private.coreservices.lsaw",@"com.apple.frontboard.launchapplications"];
    for(NSString *key in keys){
        CFTypeRef value=copy(task,(__bridge CFStringRef)key,NULL);
        result[key]=(value && CFGetTypeID(value)==CFBooleanGetTypeID() && CFBooleanGetValue(value))?@YES:@NO;
        if(value)CFRelease(value);
    }
    CFRelease(task);return result;
}

static NSDictionary *status(void) {
    return @{@"bridge":@"iossweet-development-agent", @"version":@6,
             @"guestProcessId":@(getpid()), @"guestUid":@(getuid()),
             @"vmInstanceId":configuration[@"InstanceId"] ?: @"missing",
             @"developmentOnly":@YES, @"appleProvisioningVerified":@NO,
             @"allowedBundleId":configuration[@"BundleId"] ?: @"",@"memory":processMemory(),
             @"appManagementEntitlements":effectivePrivileges ?: @{},
             @"operationPhase":[NSString stringWithUTF8String:atomic_load(&operationPhase)]};
}

static NSDictionary *operationTrace(void) {
    mach_port_t thread=atomic_load(&operationThread);
    if(thread==MACH_PORT_NULL)return @{@"phase":[NSString stringWithUTF8String:atomic_load(&operationPhase)],@"frames":@[]};
    arm_thread_state64_t registers={0};mach_msg_type_number_t count=ARM_THREAD_STATE64_COUNT;
    kern_return_t rc=thread_get_state(thread,ARM_THREAD_STATE64,(thread_state_t)&registers,&count);
    if(rc!=KERN_SUCCESS)return @{@"error":@"Own operation thread state unavailable",@"kernelResult":@(rc)};
    NSMutableArray *frames=[NSMutableArray array];
    uint64_t pc=arm_thread_state64_get_pc(registers),fp=arm_thread_state64_get_fp(registers);
    for(int i=0;i<16 && pc;i++){
        Dl_info info={0};dladdr((void*)(uintptr_t)pc,&info);
        NSString *image=info.dli_fname?[[NSString stringWithUTF8String:info.dli_fname] lastPathComponent]:@"unknown";
        NSString *symbol=info.dli_sname?[NSString stringWithUTF8String:info.dli_sname]:@"unexported";
        uint64_t offset=info.dli_fbase?pc-(uint64_t)(uintptr_t)info.dli_fbase:0;
        [frames addObject:@{@"image":image,@"symbol":symbol,@"imageOffset":[NSString stringWithFormat:@"0x%llx",(unsigned long long)offset]}];
        if(!fp || (fp&7))break;
        uint64_t pair[2]={0};vm_size_t copied=0;
        _Static_assert(sizeof(vm_address_t)==8,"The self-process trace requires 64-bit VM addresses");
        rc=vm_read_overwrite(mach_task_self(),(vm_address_t)fp,sizeof(pair),(vm_address_t)(uintptr_t)pair,&copied);
        if(rc!=KERN_SUCCESS || copied!=sizeof(pair) || pair[0]<=fp || pair[0]-fp>1048576)break;
        fp=pair[0];pc=pair[1];
    }
    return @{@"phase":[NSString stringWithUTF8String:atomic_load(&operationPhase)],@"frames":frames,@"selfProcessOnly":@YES};
}

static NSDictionary *identity(void) {
    pthread_mutex_lock(&identityMutex);
    NSDictionary *response = @{@"udid":guestUDID ?: (id)[NSNull null],
        @"source":identityState, @"vmInstanceId":configuration[@"InstanceId"],
        @"vmInstanceIdIsAppleUDID":@NO, @"appleProvisioningVerified":@NO};
    pthread_mutex_unlock(&identityMutex);
    return response;
}

static NSDictionary *listApplications(void) {
    id w = workspace();
    SEL all = NSSelectorFromString(@"allApplications");
    if (!w || ![w respondsToSelector:all]) return @{@"error":@"LaunchServices workspace unavailable"};
    NSArray *applications = ((id (*)(id,SEL))objc_msgSend)(w,all);
    NSMutableArray *result = [NSMutableArray array];
    for (id application in applications) {
        SEL identifier = NSSelectorFromString(@"bundleIdentifier");
        if (![application respondsToSelector:identifier])identifier=NSSelectorFromString(@"applicationIdentifier");
        if (![application respondsToSelector:identifier]) continue;
        NSString *name = ((id (*)(id,SEL))objc_msgSend)(application,identifier);
        if (![name isEqualToString:configuration[@"BundleId"]]) continue;
        NSMutableDictionary *entry = [@{@"bundleId":name} mutableCopy];
        SEL pathSelector = NSSelectorFromString(@"bundleURL");
        if ([application respondsToSelector:pathSelector]) {
            NSURL *url = ((id (*)(id,SEL))objc_msgSend)(application,pathSelector);
            if ([url isKindOfClass:[NSURL class]]) entry[@"path"] = [url path] ?: @"";
        }
        [result addObject:entry];
    }
    return @{@"applications":result, @"registered":result.count>0?@YES:@NO};
}

static NSDictionary *readStagedInfo(NSError **error) {
    NSString *path=[configuration[@"BundlePath"] stringByAppendingPathComponent:@"Info.plist"];
    NSData *data=[NSData dataWithContentsOfFile:path options:0 error:error];
    if(!data)return nil;
    id decoded=[NSPropertyListSerialization propertyListWithData:data options:NSPropertyListImmutable format:NULL error:error];
    return [decoded isKindOfClass:[NSDictionary class]]?decoded:nil;
}

static NSDictionary *stagedApplication(void) {
    NSString *path=[configuration[@"BundlePath"] stringByAppendingPathComponent:@"Info.plist"];
    struct stat st={0};errno=0;int rc=stat(path.fileSystemRepresentation,&st);int err=errno;
    NSError *error=nil;NSDictionary *info=readStagedInfo(&error);
    return @{@"bundlePath":configuration[@"BundlePath"],@"infoStatResult":@(rc),
        @"infoStatErrno":@(rc==0?0:err),@"infoBytes":@(st.st_size),
        @"decodedBundleId":info[@"CFBundleIdentifier"] ?: (id)[NSNull null],
        @"decodedExecutable":info[@"CFBundleExecutable"] ?: (id)[NSNull null],
        @"readError":error.localizedDescription ?: (id)[NSNull null]};
}

static NSDictionary *registerApplication(void) {
    atomic_store(&operationPhase,"reading_staged_bundle");
    NSString *bundlePath = configuration[@"BundlePath"];
    NSError *readError=nil;NSDictionary *info=readStagedInfo(&readError);
    if (![info[@"CFBundleIdentifier"] isEqual:configuration[@"BundleId"]])
        return @{@"error":@"Staged bundle does not match fixed allowlist",@"metadata":stagedApplication()};
    atomic_store(&operationPhase,"opening_LaunchServices_workspace");
    id w = workspace(); SEL selector = NSSelectorFromString(@"registerApplicationDictionary:");
    if (!w || ![w respondsToSelector:selector]) return @{@"error":@"Registration API unavailable"};
    BOOL success=NO;
    NSString *method=@"registerApplicationDictionary";
    {
        // Current LaunchServices versions consume a registration dictionary.
        // Create only this app's data container; do not enumerate/alter others.
        dlopen("/System/Library/PrivateFrameworks/MobileContainerManager.framework/MobileContainerManager",RTLD_LAZY);
        Class c=NSClassFromString(@"MCMAppDataContainer");
        SEL create=NSSelectorFromString(@"containerWithIdentifier:createIfNecessary:existed:error:");
        NSError *containerError=nil;id container=nil;
        atomic_store(&operationPhase,"creating_app_data_container");
        if(c && [c respondsToSelector:create])container=((id (*)(id,SEL,id,BOOL,BOOL*,NSError**))objc_msgSend)(c,create,configuration[@"BundleId"],YES,NULL,&containerError);
        NSURL *url=(container && [container respondsToSelector:NSSelectorFromString(@"url")])?((id (*)(id,SEL))objc_msgSend)(container,NSSelectorFromString(@"url")):nil;
        if(!url.path)return @{@"error":@"The guest did not create the app's data container",@"reason":containerError.localizedDescription ?: @"unavailable",
            @"containerErrorDomain":containerError.domain ?: @"unknown",@"containerErrorCode":@(containerError.code),
            @"containerErrorContext":containerError.userInfo.description ?: @""};
        atomic_store(&operationPhase,"building_registration_dictionary");
        NSMutableDictionary *registration=[info mutableCopy];
        registration[@"ApplicationType"]=@"System";
        registration[@"Path"]=bundlePath;registration[@"CodeInfoIdentifier"]=configuration[@"BundleId"];
        registration[@"IsContainerized"]=@YES;registration[@"Container"]=url.path;
        registration[@"EnvironmentVariables"]=@{@"HOME":url.path,@"CFFIXED_USER_HOME":url.path,@"TMPDIR":[url.path stringByAppendingPathComponent:@"tmp"]};
        registration[@"IsAdHocSigned"]=@YES;registration[@"LSInstallType"]=@1;
        registration[@"CompatibilityState"]=@0;registration[@"IsDeletable"]=@NO;
        registration[@"BundleNameIsLocalized"]=@1;
        registration[@"_LSBundlePlugins"]=@{};
        atomic_store(&operationPhase,"registering_dictionary_with_LaunchServices");
        success=((BOOL (*)(id,SEL,id))objc_msgSend)(w,NSSelectorFromString(@"registerApplicationDictionary:"),registration);
        atomic_store(&operationPhase,"registration_api_returned");
    }
    return @{@"registrationReturned":success?@YES:@NO,@"method":method, @"bundleId":configuration[@"BundleId"]};
}

static NSDictionary *launchApplication(void) {
    id w = workspace(); SEL selector = NSSelectorFromString(@"openApplicationWithBundleID:");
    if (!w || ![w respondsToSelector:selector]) return @{@"error":@"Launch API unavailable"};
    BOOL result = ((BOOL (*)(id,SEL,id))objc_msgSend)(w,selector,configuration[@"BundleId"]);
    return @{@"launchRequested":@(result), @"bundleId":configuration[@"BundleId"],
             @"screenVerified":@NO};
}

static NSDictionary *applicationProcesses(void) {
    int (*listpids)(void*,int)=dlsym(RTLD_DEFAULT,"proc_listallpids");
    int (*pidpath)(int,void*,uint32_t)=dlsym(RTLD_DEFAULT,"proc_pidpath");
    if(!listpids||!pidpath)return @{@"error":@"Process inspection unavailable"};
    int pids[2048];int count=listpids(pids,sizeof(pids));
    NSMutableArray *matches=[NSMutableArray array];
    NSString *prefix=[configuration[@"BundlePath"] stringByAppendingString:@"/"];
    for(int i=0;i<count&&i<2048;i++){
        char path[4096]={0};if(pidpath(pids[i],path,sizeof(path))<=0)continue;
        NSString *name=[NSString stringWithUTF8String:path];
        if([name hasPrefix:prefix])[matches addObject:@{@"pid":@(pids[i]),@"executable":name}];
    }
    return @{@"bundleId":configuration[@"BundleId"],@"processes":matches,@"running":matches.count>0?@YES:@NO};
}

static int sendAll(int fd, const void *bytes, size_t n) {
    const unsigned char *p=bytes;
    while (n) { ssize_t sent=send(fd,p,n,0); if(sent<=0)return -1; p+=sent; n-=(size_t)sent; }
    return 0;
}

static void reply(int fd,int code,NSDictionary *body) {
    NSData *data=[NSJSONSerialization dataWithJSONObject:body options:0 error:nil];
    if (!data) { data=[@"{\"error\":\"response failed\"}" dataUsingEncoding:NSUTF8StringEncoding]; code=500; }
    char header[320];
    int n=snprintf(header,sizeof(header),"HTTP/1.1 %d %s\r\nContent-Type: application/json\r\nContent-Length: %lu\r\nCache-Control: no-store\r\nConnection: close\r\n\r\n",code,code==200?"OK":"Error",(unsigned long)data.length);
    sendAll(fd,header,(size_t)n);sendAll(fd,data.bytes,data.length);
}

static BOOL constantEqual(NSString *left,NSString *right) {
    NSData *a=[left dataUsingEncoding:NSUTF8StringEncoding],*b=[right dataUsingEncoding:NSUTF8StringEncoding];
    if (!a || !b || a.length != b.length)return NO;
    unsigned char diff=0;const unsigned char *x=a.bytes,*y=b.bytes;
    for(NSUInteger i=0;i<a.length;i++)diff|=x[i]^y[i];
    return diff==0;
}

static void *handleClient(void *arg) {
    int fd=(int)(intptr_t)arg;
    @autoreleasepool {
        struct timeval timeout={10,0};setsockopt(fd,SOL_SOCKET,SO_RCVTIMEO,&timeout,sizeof(timeout));
        setsockopt(fd,SOL_SOCKET,SO_SNDTIMEO,&timeout,sizeof(timeout));
        char raw[16385];size_t used=0;BOOL complete=NO;
        while(used<sizeof(raw)-1){ssize_t n=recv(fd,raw+used,sizeof(raw)-1-used,0);if(n<=0)break;used+=(size_t)n;raw[used]=0;if(strstr(raw,"\r\n\r\n")){complete=YES;break;}}
        if(complete){
            NSString *request=[[NSString alloc]initWithBytes:raw length:used encoding:NSUTF8StringEncoding];
            NSArray *lines=[request componentsSeparatedByString:@"\r\n"];
            NSArray *line=[lines.firstObject componentsSeparatedByString:@" "];
            NSString *auth=nil;BOOL foreign=NO;
            for(NSString *h in lines){
                if([h.lowercaseString hasPrefix:@"authorization:"])auth=[[h substringFromIndex:14] stringByTrimmingCharactersInSet:[NSCharacterSet whitespaceCharacterSet]];
                if([h.lowercaseString hasPrefix:@"origin:"])foreign=YES;
            }
            NSString *expected=[@"Bearer " stringByAppendingString:configuration[@"Token"]];
            if(foreign || !constantEqual(auth,expected)){reply(fd,401,@{@"error":@"Unauthorized"});}
            else if(line.count!=3){reply(fd,400,@{@"error":@"Malformed request"});}
            else {
                @try {
                    NSString *method=line[0],*path=line[1];NSDictionary *result=nil;
                    if([method isEqual:@"GET"] && [path isEqual:@"/v1/status"])result=status();
                    else if([method isEqual:@"GET"] && [path isEqual:@"/v1/identity"])result=identity();
                    else if([method isEqual:@"GET"] && [path isEqual:@"/v1/processes"])result=applicationProcesses();
                    else if([method isEqual:@"GET"] && [path isEqual:@"/v1/staged"])result=stagedApplication();
                    else if([method isEqual:@"GET"] && [path isEqual:@"/v1/operation"])result=operationTrace();
                    else if(([method isEqual:@"GET"] && [path isEqual:@"/v1/apps"]) ||
                            ([method isEqual:@"POST"] && ([path isEqual:@"/v1/register"]||[path isEqual:@"/v1/launch"]))){
                        if(pthread_mutex_trylock(&operationsMutex)!=0)reply(fd,409,@{@"error":@"Another application operation is pending"});
                        else{@try{
                            __block NSDictionary *operationResult=nil;
                            dispatch_sync(dispatch_get_main_queue(), ^{
                                mach_port_t thread=mach_thread_self();atomic_store(&operationThread,thread);
                                @try { operationResult=[path isEqual:@"/v1/apps"]?listApplications():[path isEqual:@"/v1/register"]?registerApplication():launchApplication(); }
                                @catch(NSException *e){operationResult=@{@"error":e.name ?: @"app operation exception"};}
                                @finally{atomic_store(&operationThread,MACH_PORT_NULL);mach_port_deallocate(mach_task_self(),thread);}
                            });
                            result=operationResult;
                        }
                             @finally{atomic_store(&operationPhase,"idle");pthread_mutex_unlock(&operationsMutex);}}
                    }else reply(fd,404,@{@"error":@"Unknown route"});
                    if(result)reply(fd,result[@"error"]?409:200,result);
                } @catch(NSException *exception){reply(fd,500,@{@"error":exception.name ?: @"exception"});}
            }
        }
    }
    close(fd);pthread_mutex_lock(&connectionMutex);activeConnections--;pthread_mutex_unlock(&connectionMutex);
    return NULL;
}

static void *acceptConnections(void *argument) {
    int server=(int)(intptr_t)argument;
    for(;;){
        struct sockaddr_in peer;socklen_t len=sizeof(peer);int fd=accept(server,(struct sockaddr*)&peer,&len);
        if(fd<0){if(errno==EINTR)continue;break;}
        uint32_t source=ntohl(peer.sin_addr.s_addr);
        if(source!=0x0a000202 && source!=0x7f000001){close(fd);continue;}
        pthread_mutex_lock(&connectionMutex);BOOL full=activeConnections>=4;if(!full)activeConnections++;pthread_mutex_unlock(&connectionMutex);
        if(full){close(fd);continue;}
        pthread_t thread;if(pthread_create(&thread,NULL,handleClient,(void*)(intptr_t)fd)==0)pthread_detach(thread);
        else{close(fd);pthread_mutex_lock(&connectionMutex);activeConnections--;pthread_mutex_unlock(&connectionMutex);}
    }
    close(server);return NULL;
}

static void keepRunLoopAlive(void *context) {(void)context;}

int main(void) {
    configureOwnMemoryLimit();
    @autoreleasepool {
        signal(SIGPIPE,SIG_IGN);
        configuration=[NSDictionary dictionaryWithContentsOfFile:ConfigPath];
        NSString *path=configuration[@"BundlePath"],*token=configuration[@"Token"];
        if(!configuration || ![token isKindOfClass:[NSString class]] || token.length!=64 ||
           ![path hasPrefix:@"/Applications/"] || [path containsString:@".."] ||
           ![configuration[@"BundleId"] isKindOfClass:[NSString class]] ||
           ![configuration[@"InstanceId"] isKindOfClass:[NSString class]])return 64;
        effectivePrivileges=agentPrivileges();
        // Bind only to the expected QEMU private network address. Retry until
        // its VirtIO interface has been configured; no INADDR_ANY fallback.
        int server=-1;struct sockaddr_in address={0};address.sin_family=AF_INET;
        address.sin_port=htons(49160);inet_pton(AF_INET,"10.0.2.15",&address.sin_addr);
        for(int i=0;i<180;i++){
            server=socket(AF_INET,SOCK_STREAM,0);int reuse=1;setsockopt(server,SOL_SOCKET,SO_REUSEADDR,&reuse,sizeof(reuse));
            if(bind(server,(struct sockaddr*)&address,sizeof(address))==0)break;
            close(server);server=-1;sleep(2);
        }
        if(server<0 || listen(server,8)!=0)return 70;
        fprintf(stderr,"IOS_SWEET_AGENT_READY port=49160 bundle=%s\n",[configuration[@"BundleId"] UTF8String]);
        pthread_t query; if(pthread_create(&query,NULL,queryIdentity,NULL)==0)pthread_detach(query);
        pthread_t accepting;if(pthread_create(&accepting,NULL,acceptConnections,(void*)(intptr_t)server)!=0){close(server);return 70;}
        pthread_detach(accepting);
        // iOS application-management APIs are main-run-loop clients. Do not
        // block the main thread in accept() while asking an HTTP worker to
        // synchronously marshal registration work back onto that thread.
        CFRunLoopSourceContext context={0};context.perform=keepRunLoopAlive;
        CFRunLoopSourceRef source=CFRunLoopSourceCreate(kCFAllocatorDefault,0,&context);
        CFRunLoopAddSource(CFRunLoopGetMain(),source,kCFRunLoopCommonModes);
        CFRunLoopRun();CFRelease(source);
    }
    return 0;
}
