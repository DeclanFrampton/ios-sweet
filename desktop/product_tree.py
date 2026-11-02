"""Prepare this user's pinned iPhone X product tree; never ship Apple firmware.

Source-run Studio must not depend on research/ipsw-x on a developer's PC.
Only the small DeviceTree component is fetched when repairing an already
created device. The filesystem, overlay and installed apps are not touched.
"""
from __future__ import annotations
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
import uuid

IM4P_SHA256='480e8b0888949b4128b7aa2cd254497581c69e1bafa596a760b2fa955a8a6368'
ADT_SHA256='9e670987c80493bd69aba7be62e3179c04663324d9249b0973675baac175dbf1'
ADT_BYTES=186084
MEMBER='Firmware/all_flash/DeviceTree.d22ap.im4p'
LZFSE_SHA256='255b3a288739cfbfb989a9d4881c693a36312743ac41bd96945659ca8ce52df8'


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def validate(path):
    path=Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size!=ADT_BYTES or digest(path)!=ADT_SHA256:
        raise ValueError('The private iPhone X device tree is missing or does not match iOS 16.7.16. '
                         'Its existing file was not overwritten: '+str(path))
    return path.resolve()


def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


def ensure(home,resource,report=print,existing=None):
    """Repair a missing product ADT without recreating an existing iOS disk."""
    if existing and Path(existing).exists():return validate(existing)
    home,resource=Path(home).resolve(),Path(resource).resolve()
    folder=home/'boot-assets'
    if folder.is_symlink():raise ValueError('Private boot-assets folder must not be a symbolic link.')
    folder.mkdir(parents=True,exist_ok=True)
    target=folder/'d22ap-20H392.adt'
    if target.exists() or target.is_symlink():return validate(target)
    import runtime_setup
    asset,_=runtime_setup.asset_paths(resource)
    decoder=asset/'lzfse.exe'
    manifest=json.loads((asset/'manifest.json').read_text(encoding='utf-8'))
    if not decoder.is_file() or digest(decoder)!=manifest.get('lzfse.exe'):
        raise RuntimeError('The native firmware decoder is missing or changed. Close Studio, '
                           'run git pull --ff-only, then start.cmd to obtain runtime r3. Keep your existing device data.')
    tools=resource/'tools'
    sys.path.insert(0,str(tools))
    apple=load('_studio_product_apple',tools/'AutoPrepare-IosSweet.py')
    cached=home/'firmware-cache/firmware'/MEMBER
    if not cached.is_file():
        report('Preparing missing iPhone product capabilities: fetching the 33 KB device tree from Apple; existing disk stays unchanged')
        dest,entries,wanted=apple.get_manifest(home/'firmware-cache')
        if wanted['dt']!=MEMBER or entries[MEMBER][3]!=33719:
            raise RuntimeError('Unexpected device-tree component in Apple firmware manifest.')
        cached=apple.extract_member(dest,entries,MEMBER)
    if cached.is_symlink() or cached.stat().st_size!=33719 or digest(cached)!=IM4P_SHA256:
        raise RuntimeError('Cached Apple device-tree component failed its pinned checksum. '
                           'No disk was changed. Preserve the log and the firmware cache for diagnosis.')
    report('Verifying and unpacking private iPhone X product capabilities')
    extractor=load('_studio_product_extract',tools/'extract-im4p-adt.py')
    stage=folder/('.prepare-'+uuid.uuid4().hex);stage.mkdir()
    try:
        candidate=stage/'product.adt'
        extractor.extract(cached,candidate,str(decoder))
        validate(candidate)
        # Never replace an unknown file even if another Studio populated it.
        if target.exists():validate(target)
        else:os.replace(candidate,target)
    finally:
        if stage.parent.resolve()!=folder.resolve() or stage.is_symlink():raise RuntimeError('Unsafe product-tree cleanup path')
        shutil.rmtree(stage)
    report('iPhone product capabilities verified; existing iOS disk and apps are unchanged')
    return validate(target)
