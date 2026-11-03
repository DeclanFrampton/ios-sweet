"""CPU/RAM/disk warm-resume probe. Uses only new disposable artifacts.

Runs a tiny ARM loop, snapshots it, changes cold RAM and disk state, and
relaunches QEMU to verify restoration and continued execution. Never accepts
an existing disk. Timings do not represent iOS or a populated 7-GiB guest.
"""
import argparse,json,pathlib,re,socket,subprocess,tempfile,time

def run(qemu, img, output):
    out=pathlib.Path(output).resolve(); out.mkdir(parents=True,exist_ok=False)
    # Refuse reuse: this tool must never operate on an existing guest disk.
    disk=out/'synthetic.qcow2'
    if disk.exists(): raise RuntimeError('Output already contains a disk; choose a new directory')
    subprocess.run([img,'create','-f','qcow2',str(disk),'16M'],check=True,capture_output=True)
    marker=out/'marker.bin'; marker.write_bytes(b'ORIGINAL-RAM-STATE')
    # add x0,x0,#1; b .-4. Real execution makes CPU restoration observable.
    program=out/'loop.bin'; program.write_bytes(bytes.fromhex('00040091ffffff17'))
    saved_registers=None
    result={'scope':'synthetic executing ARM VM, CPU/RAM/disk restart; no iOS boot','runs':[]}
    for phase in ['save','restore']:
        if phase=='restore': marker.write_bytes(b'DIFFERENT-COLD-RAM')
        with socket.socket() as reserve:
            reserve.bind(('127.0.0.1',0)); port=reserve.getsockname()[1]
        argv=[qemu,'-M','virt,gic-version=3','-accel','tcg,thread=multi','-cpu','cortex-a76','-smp','2','-m','128M','-S','-display','none','-serial','none','-monitor','none','-nic','none','-global','virtio-mmio.force-legacy=false','-qmp',f'tcp:127.0.0.1:{port},server=on,wait=off','-device',f'loader,file={marker.as_posix()},addr=0x40200000,force-raw=on','-drive',f'if=none,id=iosroot,format=qcow2,file={disk.as_posix()}','-device','virtio-blk-device,drive=iosroot','-device','virtio-tablet-device,id=sweet-tablet','-netdev','user,id=sweetnet,net=10.0.2.0/24','-device','virtio-net-device,netdev=sweetnet,mac=02:50:53:57:00:01']
        started=time.perf_counter()
        argv += ['-device',f'loader,file={program.as_posix()},addr=0x40300000,force-raw=on',
                 '-device','loader,addr=0x40300000,cpu-num=0']
        with (out/(phase+'.log')).open('w') as log:
            p=subprocess.Popen(argv,stdout=log,stderr=subprocess.STDOUT)
            try:
                for _ in range(100):
                    try: s=socket.create_connection(('127.0.0.1',port),timeout=1); break
                    except OSError:
                        if p.poll() is not None: raise RuntimeError('QEMU exited')
                        time.sleep(.05)
                else: raise TimeoutError('QMP')
                f=s.makefile('rwb'); f.readline()
                def command(name,args=None):
                    f.write((json.dumps({'execute':name,'arguments':args or {}})+'\n').encode()); f.flush()
                    while True:
                        response=json.loads(f.readline())
                        if 'error' in response: raise RuntimeError(response)
                        if 'return' in response: return response['return']
                command('qmp_capabilities')
                def hmp(line):
                    return command('human-monitor-command',{'command-line':line})
                def registers():
                    return hmp('info registers').strip()
                def counter():
                    return int(re.search(r'X00=([0-9a-fA-F]+)',registers()).group(1),16)
                def disk_io(operation):
                    response=hmp('qemu-io iosroot "'+operation+'"')
                    if any(word in response.lower() for word in ('error','failed','not found','not supported','mismatch')):
                        raise RuntimeError(response)
                    return response
                disk_io('write -P '+('0x41' if phase=='save' else '0x42')+' 0 512')
                disk_io('read -P '+('0x41' if phase=='save' else '0x42')+' 0 512')
                if phase=='save':
                    command('cont'); time.sleep(.1); command('stop')
                    assert counter()>0,'ARM loop never executed'
                    saved_registers=registers()
                before=out/(phase+'-before.bin')
                command('pmemsave',{'val':0x40200000,'size':32,'filename':before.as_posix()})
                assert before.read_bytes().startswith(marker.read_bytes()), 'Cold RAM marker mismatch'
                t=time.perf_counter()
                response=command('human-monitor-command',{'command-line':('savevm' if phase=='save' else 'loadvm')+' offline-test'})
                elapsed=time.perf_counter()-t
                capture=out/(phase+'-ram.bin')
                command('pmemsave',{'val':0x40200000,'size':32,'filename':capture.as_posix()})
                actual=capture.read_bytes()[:len(b'ORIGINAL-RAM-STATE')]
                if response: raise RuntimeError(response)
                assert actual==b'ORIGINAL-RAM-STATE',actual
                assert registers()==saved_registers,'CPU state differs from saved state'
                disk_read=disk_io('read -P 0x41 0 512')
                before_counter=counter()
                command('cont'); time.sleep(.1); command('stop')
                after_counter=counter()
                assert after_counter>before_counter,'Restored CPU did not continue execution'
                result['runs'].append({'phase':phase,'snapshot_seconds':elapsed,'total_seconds':time.perf_counter()-started,'ram_restored':actual.decode(),'cpu_state_matches':True,'counter_before':before_counter,'counter_after':after_counter,'disk_read':disk_read})
                command('quit'); f.close(); s.close(); p.wait(timeout=10)
            finally:
                if p.poll() is None: p.terminate(); p.wait(timeout=10)
        # qemu-io writes its verification output to stdout, not the HMP reply.
        log_text=(out/(phase+'.log')).read_text()
        assert log_text.count('read 512/512 bytes')==2,log_text
        assert log_text.count('wrote 512/512 bytes')==1,log_text
        assert not re.search(r'fail|error|mismatch|pattern verification',log_text,re.I),log_text
        result['runs'][-1]['disk_pattern_verified']=True
        result['runs'][-1].pop('disk_read')
    result['snapshot']=json.loads(subprocess.check_output([img,'info','--output=json',str(disk)]))
    (out/'result.json').write_text(json.dumps(result,indent=2)); print(json.dumps(result,indent=2))
if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('--qemu',required=True); parser.add_argument('--qemu-img',required=True); parser.add_argument('--output',required=True); a=parser.parse_args(); run(a.qemu,a.qemu_img,a.output)
