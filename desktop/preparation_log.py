"""Bounded, redacted setup diagnostics and a non-blocking subprocess monitor.

A living PID/CPU counter is activity, not proof of useful progress. No overall
percentage is invented. Only the subprocess returned by Popen is terminated.
"""
from __future__ import annotations
import codecs
from collections import deque
import ctypes
import datetime
import json
import os
from pathlib import Path
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid

HIDDEN=getattr(subprocess,'CREATE_NO_WINDOW',0)
MAX_LOG=8*1024**2
MAX_LINE=4096
ANSI=re.compile(r'\x1b\[[0-?]*[ -/]*[@-~]')


def redact(text):
    text=ANSI.sub('',str(text))
    text=re.sub(r'(?i)(Bearer\s+)[^\s,;"<>]+',r'\1[redacted]',text)
    text=re.sub(r'(?i)((?:token|password|secret|api[_-]?key)["\s:=]+)[^\s,;}<]+',r'\1[redacted]',text)
    text=re.sub(r'\b[0-9a-fA-F]{64}\b','[redacted-64hex]',text)
    return ''.join(c for c in text if c in '\n\t' or ord(c)>=32)


def utc():return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')


def confined(home,relative):
    home=Path(home).resolve()
    if not isinstance(relative,str) or Path(relative).is_absolute():raise ValueError('Invalid diagnostic path')
    path=(home/relative).resolve()
    if not path.is_relative_to(home) or path==home:raise ValueError('Diagnostic path leaves the workspace')
    return path


def read_latest(home,tail=False):
    """Read only the saved setup log selected by our writer; never a caller path."""
    try:
        pointer=confined(home,'logs/preparation-latest.json')
        if not pointer.is_file():return None
        if pointer.stat().st_size>65536:return None
        state=json.loads(pointer.read_text(encoding='utf-8'))
        if state.get('schema')!=1:return None
        log=confined(home,state['logFile'])
        expected=Path('logs')/'preparation'/state['runId']/'preparation.log'
        if Path(state['logFile'])!=expected or not re.fullmatch('[0-9a-f]{32}',state['runId']):return None
        now=time.time();state['elapsedSeconds']=max(0,int(state.get('finishedEpoch',now)-state['startedEpoch']))
        state['heartbeatAgeSeconds']=max(0,int(now-state['updatedEpoch']))
        stamp=state.get('lastOutputEpoch')
        state['outputAgeSeconds']=max(0,int(now-stamp)) if stamp else None
        state['stale']=state['status']=='running' and state['heartbeatAgeSeconds']>30
        if tail:
            if log.is_file():
                with log.open('rb') as f:
                    f.seek(max(0,log.stat().st_size-65536));data=f.read(65536)
                state['tail']=redact(data.decode('utf-8',errors='replace'))[-65536:]
            else:state['tail']='The preparation log has not been created yet.'
        return state
    except (OSError,ValueError,KeyError,TypeError):return None


class PreparationLog:
    def __enter__(self):return self

    def __exit__(self,kind,error,tb):
        self.finish('failed' if error else 'succeeded',str(error) if error else None)
        return False

    def __init__(self,home,mode,report=print):
        self.home=Path(home).resolve();output=sys.stdout
        self.report=report if report is not print else lambda text:print(text,file=output,flush=True)
        self.lock=threading.RLock()
        self.run_id=uuid.uuid4().hex
        self.folder=confined(self.home,'logs/preparation/'+self.run_id);self.folder.mkdir(parents=True)
        self.path=self.folder/'preparation.log';self.pointer=confined(self.home,'logs/preparation-latest.json')
        self.state={'schema':1,'runId':self.run_id,'mode':mode,'status':'running','stage':'Starting setup',
            'startedAt':utc(),'startedEpoch':time.time(),'updatedEpoch':time.time(),'lastOutputEpoch':None,
            'stageStartedEpoch':time.time(),'processId':None,'exitCode':None,'cpuSeconds':None,
            'readBytes':None,'writeBytes':None,'activity':'Starting','message':'Starting setup',
            'logFile':self.path.relative_to(self.home).as_posix()}
        self.last_report=0.;self.last_write=0.;self.tail=deque(maxlen=12)
        self.write('Setup diagnostics started. Activity does not imply successful installation.')

    def persist(self):
        self.state['updatedEpoch']=time.time();self.state['updatedAt']=utc()
        text=json.dumps(self.state,indent=2)
        for path in (self.folder/'status.json',self.pointer):
            temporary=path.with_suffix('.'+uuid.uuid4().hex+'.new')
            temporary.write_text(text,encoding='utf-8')
            os.replace(temporary,path)

    def write(self,message,output=False,publish=False):
        clean=redact(str(message))[:MAX_LINE].strip()
        if not clean:return
        with self.lock:
            if self.path.exists() and self.path.stat().st_size>MAX_LOG:
                os.replace(self.path,self.folder/'preparation.previous.log')
            with self.path.open('a',encoding='utf-8') as f:f.write(utc()+' '+clean+'\n')
            self.tail.append(clean)
            if output:self.state['lastOutputEpoch']=time.time()
            self.state['message']=clean
            if publish or time.monotonic()-self.last_write>=.5:
                self.persist();self.last_write=time.monotonic()
            if publish or time.monotonic()-self.last_report>=2:
                self.report(clean);self.last_report=time.monotonic()

    def __call__(self,message):self.write(message,output=True)

    def stage(self,name):
        with self.lock:
            self.state.update(stage=redact(name)[:200],stageStartedEpoch=time.time())
            self.state.pop('copyProgress',None)
            self.write('Stage: '+name,publish=True)

    def finish(self,status,error=None):
        with self.lock:
            self.state.update(status=status,finishedEpoch=time.time(),activity='Finished' if status=='succeeded' else 'Stopped')
            if error:self.state['error']=redact(error)[:2000]
            self.write('Setup '+status+(': '+str(error) if error else ''),publish=True)

    def consume(self,line):
        line=redact(line).strip()
        if line.startswith('STUDIO_STAGE '):
            self.state['namedStages']=True;self.stage(line[len('STUDIO_STAGE '):])
        elif line.startswith('COPYING '):self.stage('Copying '+line[8:]+' files')
        elif line.startswith('PREPARE_STEP ') and not self.state.get('namedStages'):self.stage(line[13:])
        elif line=='STUDIO_PREPARER_STARTED':self.stage('Setup engine booted; reading the preparation job')
        elif line=='ASSEMBLING_PRIVATE_IOS_ROOT':self.stage('Mounting Apple firmware images')
        elif line=='STUDIO_AGENT_SEEDED':self.stage('App-management and network services installed')
        elif line=='PRIVATE_MG_COMPAT_VERIFIED':self.stage('Compatibility patch checksum verified')
        # rsync's progress2 percentage belongs only to this copy operation,
        # not the entire firmware preparation, and can revise its file total.
        match=re.search(r'^\s*([\d,]+)\s+(\d{1,3})%\s+([\d.]+\S+/s)',line)
        if match and int(match[2])<=100:
            self.state['copyProgress']={'bytes':int(match[1].replace(',','')),'percent':int(match[2]),'rate':match[3]}
        self.write(line,output=True)


class WindowsActivity:
    def __init__(self,pid):
        self.handle=None
        if os.name!='nt':return
        from ctypes import wintypes as w
        self.k=ctypes.WinDLL('kernel32',use_last_error=True)
        class IO(ctypes.Structure):
            _fields_=[(n,ctypes.c_ulonglong) for n in ('readOps','writeOps','otherOps','readBytes','writeBytes','otherBytes')]
        self.io=IO;self.ft=w.FILETIME
        self.k.OpenProcess.argtypes=[w.DWORD,w.BOOL,w.DWORD];self.k.OpenProcess.restype=w.HANDLE
        self.k.GetProcessIoCounters.argtypes=[w.HANDLE,ctypes.POINTER(IO)]
        self.k.GetProcessTimes.argtypes=[w.HANDLE,*([ctypes.POINTER(w.FILETIME)]*4)]
        self.k.CloseHandle.argtypes=[w.HANDLE]
        self.handle=self.k.OpenProcess(0x1000,False,pid)

    def sample(self):
        if not self.handle:return {}
        io=self.io();created=self.ft();exited=self.ft();kernel=self.ft();user=self.ft();out={}
        if self.k.GetProcessTimes(self.handle,ctypes.byref(created),ctypes.byref(exited),ctypes.byref(kernel),ctypes.byref(user)):
            ticks=lambda t:(t.dwHighDateTime<<32)+t.dwLowDateTime
            out['cpuSeconds']=round((ticks(kernel)+ticks(user))/10**7,1)
        if self.k.GetProcessIoCounters(self.handle,ctypes.byref(io)):
            out.update(readBytes=io.readBytes,writeBytes=io.writeBytes)
        return out

    def close(self):
        if self.handle:self.k.CloseHandle(self.handle);self.handle=None


def monitor(command,diagnostic,stage,timeout=7200,success_marker=None,heartbeat=5,quiet_after=90):
    """Drain raw stdout/stderr even without newline; keep heartbeat independent.

    Return only after exit 0 and, when required, the explicit completion marker.
    A panic, EOF, launch error and deadline each retain their actual diagnosis.
    """
    diagnostic.stage(stage)
    try:
        process=subprocess.Popen(list(map(str,command)),stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,bufsize=0,creationflags=HIDDEN)
    except OSError as error:
        diagnostic.write('Cannot start '+Path(command[0]).name+': '+str(error),publish=True);raise
    diagnostic.state.update(processId=process.pid,processName=Path(command[0]).name,exitCode=None)
    diagnostic.write('Started '+Path(command[0]).name+' (PID '+str(process.pid)+'). Timeout: '+str(int(timeout))+'s.',publish=True)
    stream=queue.Queue(maxsize=64);stopping=threading.Event()
    def enqueue(item):
        while not stopping.is_set():
            try:stream.put(item,timeout=.2);return
            except queue.Full:pass
    def reader():
        try:
            while not stopping.is_set():
                data=process.stdout.read(4096)
                if not data:break
                enqueue(data)
        except (OSError,ValueError) as e:enqueue(('read_error',str(e)))
        finally:enqueue(None)
    thread=threading.Thread(target=reader,daemon=True);thread.start()
    activity=WindowsActivity(process.pid);started=time.monotonic();last_output=started
    beat=started;pending='';last_partial='';decoder=codecs.getincrementaldecoder('utf-8')('replace')
    eof=False;success=not success_marker;fatal=None;previous={}
    def line(text):
        nonlocal success,fatal
        text=text.strip()
        if not text:return
        diagnostic.consume(text)
        if success_marker and text==success_marker:success=True
        if ('Kernel panic - not syncing' in text or text=='STUDIO_PREPARER_FAILED'
            or ('rom:' in text and 'Failed to open file' in text)
            or 'could not load PC BIOS' in text):fatal=text
    try:
        while True:
            now=time.monotonic()
            if now-started>=timeout:
                raise TimeoutError('Timed out after '+str(int(timeout))+'s during '+diagnostic.state['stage']+
                    '. Last output '+str(int(now-last_output))+'s ago. See '+str(diagnostic.path))
            try:item=stream.get(timeout=min(.25,heartbeat,max(.01,timeout-(now-started))))
            except queue.Empty:item=b''
            if item is None:eof=True
            elif isinstance(item,tuple):raise RuntimeError('Could not read setup output: '+item[1])
            elif item:
                last_output=time.monotonic();diagnostic.state['lastOutputEpoch']=time.time();pending+=decoder.decode(item)
                # rsync/qemu-img report carriage-return updates rather than lines.
                parts=re.split(r'[\r\n]',pending);pending=parts.pop()
                for text in parts:line(text)
                if len(pending)>MAX_LINE:line(pending[:MAX_LINE]);pending=''
            if fatal:raise RuntimeError('Setup engine reported: '+fatal+'. See '+str(diagnostic.path))
            now=time.monotonic()
            if now-beat>=heartbeat:
                sample=activity.sample();quiet=max(0,now-last_output);silence=int(quiet)
                changed=bool(previous and any(sample.get(k,0)>previous.get(k,0) for k in sample))
                diagnostic.state.update(sample)
                diagnostic.state.update(activity='Process activity detected' if changed else 'Process running; progress unconfirmed',
                    quietSeconds=silence)
                try:diagnostic.state['freeBytes']=shutil.disk_usage(diagnostic.home).free
                except OSError:pass
                message='Heartbeat: '+str(int(now-started))+'s in this process; no new console output for '+str(silence)+'s.'
                if 'cpuSeconds' in sample:message+=' CPU time '+str(sample['cpuSeconds'])+'s.'
                if 'writeBytes' in sample:message+=' OS-reported writes '+str(round(sample['writeBytes']/1048576,1))+' MiB.'
                if quiet>=quiet_after:message+=' Quiet stage: progress is not confirmed. Open the preparation log for details.'
                diagnostic.write(message,publish=True);previous=sample;beat=now
                if pending and pending!=last_partial:
                    diagnostic.write('[partial output] '+pending);last_partial=pending
            if eof and process.poll() is not None:break
        if pending:line(pending+decoder.decode(b'',final=True))
        if fatal:raise RuntimeError('Setup engine reported: '+fatal+'. See '+str(diagnostic.path))
        code=process.wait(timeout=5);diagnostic.state.update(exitCode=code,activity='Process exited',**activity.sample())
        diagnostic.write('Process '+str(process.pid)+' exited with code '+str(code)+'.',publish=True)
        if code:raise RuntimeError('Setup process exited with code '+str(code)+' during '+diagnostic.state['stage']+
            '. Last output: '+' | '.join(list(diagnostic.tail)[-4:])[:1200]+'. Log: '+str(diagnostic.path))
        if not success:raise RuntimeError('Setup exited without '+success_marker+'. No device was marked ready. Log: '+str(diagnostic.path))
        return code
    finally:
        if process.poll() is None:
            diagnostic.write('Stopping only the setup subprocess launched for this operation (PID '+str(process.pid)+').',publish=True)
            process.terminate()
            try:process.wait(timeout=5)
            except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
        diagnostic.state['exitCode']=process.returncode;diagnostic.persist()
        stopping.set();thread.join(timeout=2);process.stdout.close();activity.close()
