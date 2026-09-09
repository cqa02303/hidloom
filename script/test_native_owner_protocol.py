#!/usr/bin/env python3
"""Real native owner + real InteractionEngine, isolated sockets and fixture HID.

No device access, service mutation, or host keyboard injection is performed.
"""
from __future__ import annotations
import asyncio
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'daemon'),str(ROOT),str(ROOT/'script')]
from test_logicd_core_rs_tool import BIN, build_tool, core_env, flat_keymap, wait_for_socket
from logicd.delegate_protocol import DelegateSession
from logicd.input_events import InputEventContext
from logicd.interaction_engine import InteractionEngine
from logicd.keymap import LayerManager


_native_built = False


def ensure_native_built():
    global _native_built
    if "HIDLOOM_TEST_CORE_BINARY" not in os.environ and not _native_built:
        build_tool()
        _native_built = True


class Fixture:
    def __init__(self,layers,*,delegate=True,lease=30000):
        self.layers=layers;self.use_delegate=delegate;self.lease=lease
        self.messages=[];self.effects=[];self.connections=[];self.block=None;self.ack_override=None
        self.duplicate_ack=False

    async def __aenter__(self):
        ensure_native_built()
        self.directory=tempfile.TemporaryDirectory();self.root=Path(self.directory.name)
        self.ctrl=self.root/'ctrl.sock';self.matrix=self.root/'matrix.sock';self.sink=self.root/'sink.sock'
        env=core_env(self.root,flat_keymap(self.layers))
        status=self.root/'output.json'
        status.write_text(json.dumps({'process':True,'target':'auto','effective_target':'usb','last_error':'',
            'readiness':{'usb':'ready','pending_usb_neutral':False}}))
        env.update(LOGICD_CORE_CTRL_SOCKET=str(self.ctrl),LOGICD_CORE_MATRIX_SOCKET=str(self.matrix),
            LOGICD_CORE_HID_REPORT_SOCKET=str(self.sink),LOGICD_CORE_OUTPUT_ENABLED='1',
            LOGICD_CORE_OUTPUT_STATUS_PATH=str(status),LOGICD_CORE_STATUS_PATH=str(self.root/'status.json'),
            LOGICD_CORE_SOURCE_LEASE_MS=str(self.lease),LOGICD_CORE_DELEGATE_SOCKET=str(self.root/'delegate.sock') if self.use_delegate else 'none')
        self.broker=socket.socket(socket.AF_UNIX,socket.SOCK_DGRAM);self.broker.bind(str(self.sink));self.broker.setblocking(False)
        layers=LayerManager();layers.load(self.layers)
        async def handle(action,pressed):self.effects.append((action,pressed))
        noop=lambda *args:None
        self.ctx=InputEventContext(layers,InteractionEngine(layers,tapping_term=0.040),
            SimpleNamespace(handle=handle),SimpleNamespace(handles=lambda *_:False),None,set(),
            noop,noop,noop,noop,noop,lambda *_:False,noop,bt_manager=None)
        self.session=DelegateSession(lambda:self.ctx)
        self.server=await asyncio.start_unix_server(self.handle_delegate,path=str(self.root/'delegate.sock')) if self.use_delegate else None
        binary=os.environ.get('HIDLOOM_TEST_CORE_BINARY',str(BIN))
        self.process=subprocess.Popen([binary,'--serve'],env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        await asyncio.to_thread(wait_for_socket,self.ctrl)
        return self

    async def handle_delegate(self,reader,writer):
        self.connections.append(writer)
        try:
            while line:=await reader.readline():
                message=json.loads(line);self.messages.append(message)
                if self.block is not None:await self.block.wait()
                response=await self.session.process(message)
                if self.ack_override:response=self.ack_override(response)
                writer.write(json.dumps(response).encode()+b'\n');await writer.drain()
                if self.duplicate_ack:writer.write(json.dumps(response).encode()+b'\n');await writer.drain()
        except (BrokenPipeError,ConnectionResetError,asyncio.CancelledError):pass
        finally:writer.close()

    async def __aexit__(self,*_):
        if self.block:self.block.set()
        self.process.terminate();await asyncio.to_thread(self.process.communicate,timeout=3)
        for writer in self.connections:writer.close()
        if self.server:self.server.close();await self.server.wait_closed()
        self.broker.close();self.directory.cleanup()

    async def request(self,payload,connection=None):
        own=connection is None
        reader,writer=connection or await asyncio.open_unix_connection(str(self.ctrl))
        try:
            writer.write(json.dumps(payload).encode()+b'\n');await writer.drain()
            return json.loads(await asyncio.wait_for(reader.readline(),2))
        finally:
            if own:writer.close();await writer.wait_closed()

    async def open_source(self):
        connection=await asyncio.open_unix_connection(str(self.ctrl))
        result=await self.request({'t':'source_open','protocol':1},connection)
        assert result['result']=='ok',result
        return connection

    async def event(self,press,col=0,source=None):
        if source:
            result=await self.request({'t':'source_event','row':0,'col':col,'is_press':press},source)
            assert result['result']=='ok',result
        else:
            _,writer=await asyncio.open_unix_connection(str(self.matrix))
            writer.write(f'{"P" if press else "R"}0{col:x}\n'.encode());await writer.drain();writer.close();await writer.wait_closed()

    async def report(self,timeout=2):
        packet=await asyncio.wait_for(asyncio.get_running_loop().sock_recv(self.broker,128),timeout)
        assert packet[:4]==b'CQAU' and packet[4:7]==bytes([1,1,8]),packet
        return packet[8:16]

    async def quiet(self):
        try:report=await self.report(.025)
        except asyncio.TimeoutError:return
        raise AssertionError(f'unexpected fixture report {report.hex()}')

    async def until(self,predicate):
        deadline=time.monotonic()+2
        while time.monotonic()<deadline:
            state=await self.request({'t':'owner_state','row':0,'col':0})
            if predicate(state):return state
            await asyncio.sleep(.002)
        raise AssertionError(state)


async def sessions_and_guard():
    async with Fixture([{'0,0':'KC_A','0,1':'KC_B'}],delegate=False) as f:
        first,second=await f.open_source(),await f.open_source()
        await f.event(True,source=first);assert (await f.report())[2]==4
        await f.event(True,source=first);await f.event(True,source=second);await f.event(True)
        await f.quiet()
        first[1].close();await first[1].wait_closed();await f.quiet()
        second[1].close();await second[1].wait_closed();await f.quiet()
        await f.event(False);assert await f.report()==bytes(8)
        # Raw one-shot producer EOF retains its press until its later raw release.
        await f.event(True);assert (await f.report())[2]==4
        await f.quiet();await f.event(False);assert await f.report()==bytes(8)
        state=await f.request({'t':'owner_state','row':0,'col':0})
        tap={'t':'guarded_tap','operation_id':'one-tap','row':0,'col':0,'expected_action':'KC_A','hold_ms':100,
             **{'expected_'+key:state[key] for key in ('owner_epoch','keymap_revision','layer_revision','output_revision')}}
        bad=dict(tap,expected_layer_revision=0)
        assert (await f.request(bad))['state']=='rejected';await f.quiet()
        assert (await f.request(tap))['state']=='started';assert (await f.report())[2]==4
        assert (await f.request(tap))['state']=='started';await f.quiet()
        await f.event(True,1)
        assert await f.report()==bytes(8), 'synthetic press must end before physical B'
        assert (await f.report())[2]==5
        assert (await f.request(tap))['state']=='released'
        await f.event(False,1);assert await f.report()==bytes(8)
        tap=dict(tap,operation_id='client-death')
        reader,writer=await asyncio.open_unix_connection(str(f.ctrl))
        writer.write(json.dumps(tap).encode()+b'\n');await writer.drain();writer.close();await writer.wait_closed()
        assert (await f.report())[2]==4
        assert await f.report()==bytes(8)
        assert (await f.request({'t':'operation_status','operation_id':'client-death'}))['state']=='released'


async def source_revision_and_lease():
    async with Fixture([{'0,0':'KC_A'}],delegate=False,lease=100) as f:
        first=await f.open_source();await f.event(True,source=first);assert (await f.report())[2]==4
        state=await f.request({'t':'owner_state'})
        result=await f.request({'t':'apply_keymap','operation_id':'remap','layers':[{'0,0':'KC_B'}],
            'expected_owner_epoch':state['owner_epoch'],'expected_keymap_revision':state['keymap_revision']})
        assert result['result']=='ok'
        second=await f.open_source();await f.event(True,source=second);report=await f.report();assert set(report[2:])=={0,4,5}
        first[1].close();await first[1].wait_closed();report=await f.report();assert 4 not in report and 5 in report
        assert await f.report()==bytes(8), 'lease expiry releases second source only'
        second[1].close()


async def real_interaction_transactions():
    layers=[{'0,0':'MO(1)','0,1':'KC_A','0,2':'LT(1,KC_B)','0,3':'KC_C','0,4':'KC_LSFT','0,5':'OSL(1)'},
            {'0,1':'KC_CONSOLE','0,3':'KC_D'}]
    async with Fixture(layers) as f:
        f.ctx.output_transition_fn=lambda:f.request({'t':'output_transition'})
        await f.event(True,0);await f.event(True,1)
        await f.until(lambda state: not state['delegate_transaction']['pending'])
        assert f.effects.count(('KC_CONSOLE',True))==1
        assert f.messages[0]['action']=='KC_CONSOLE'
        assert (await f.request({'t':'owner_state'}))['output_revision']==2
        await f.quiet()
        await f.event(False,1);await f.event(False,0)
        await f.until(lambda state:state['idle'])
        # Real InteractionEngine timer -> MO commit ACK -> subsequent context key.
        await f.event(True,2)
        await f.until(lambda state:1 in state['layer_state']['momentary'])
        assert any(message['t']=='delegate_tick' for message in f.messages)
        await f.event(True,3);assert (await f.report())[2]==7
        await f.event(False,3);assert await f.report()==bytes(8)
        await f.event(False,2);await f.until(lambda state:state['idle'])
        # Interrupting a pending LT commits its hold before resolving this key.
        await f.event(True,2);await f.event(True,3)
        assert (await f.report())[2]==7
        await f.event(False,3);assert await f.report()==bytes(8)
        await f.event(False,2);await f.until(lambda state:state['idle'])
        # LT tap schedules real report spacing on native loop, without blocking.
        await f.event(True,2);await f.event(False,2)
        assert (await f.report())[2]==5;started=time.monotonic()
        assert await f.report()==bytes(8)
        elapsed=time.monotonic()-started
        assert elapsed>=.055, 'existing synthetic tap spacing collapsed (native unit checks exact60ms)'
        print(f'LT tap captured receipt spacing: {elapsed*1000:.3f} ms')
        await f.until(lambda state:state['idle'])
        # OSL survives a native modifier and is consumed by its first nonmodifier.
        await f.event(True,5);await f.event(False,5);await f.event(True,4)
        assert (await f.report())[0]==2
        state=await f.request({'t':'owner_state'});assert state['layer_state']['oneshot']==[1]
        await f.event(True,3);report=await f.report();assert report[0]==2 and 7 in report
        assert (await f.request({'t':'owner_state'}))['layer_state']['oneshot']==[]
        await f.event(False,3);assert (await f.report())[0]==2
        await f.event(False,4);assert await f.report()==bytes(8)


async def stalled_delegate_preserves_native_release():
    async with Fixture([{'0,0':'KC_A','0,1':'LT(1,KC_B)'},{}]) as f:
        await f.event(True);assert (await f.report())[2]==4
        f.block=asyncio.Event();await f.event(True,1)
        await f.until(lambda state:state['delegate_transaction']['pending'])
        started=time.monotonic();await f.event(False)
        assert await f.report(.1)==bytes(8)
        elapsed=time.monotonic()-started
        assert not f.block.is_set(), 'known release must not wait for companion ACK'
        await f.until(lambda state:state['delegate_transaction']['last_error']=='delegate_ack_timeout')
        await f.quiet()
        print(f'stalled companion known-release fixture: {elapsed*1000:.3f} ms')


async def delegated_disconnect_and_delayed_press_cleanup():
    async with Fixture([{'0,0':'KC_C','0,1':'LCTL(KC_A)'}]) as f:
        await f.event(True);assert (await f.report())[2]==6
        source=await f.open_source();await f.event(True,1,source)
        first=await f.report();assert first[0]==1 and 6 in first
        source[1].close();await source[1].wait_closed()
        released=await f.report();assert released[0]==0 and 6 in released
        await f.until(lambda state:state['delegated']==0 and state['injected']==0)
        await f.quiet()  # delayed wrapper A must never appear after source EOF
        await f.event(False);assert await f.report()==bytes(8)


async def stale_ack_and_scoped_failure():
    async with Fixture([{'0,0':'KC_C','0,1':'LT(1,KC_B)'},{}]) as f:
        await f.event(True);assert (await f.report())[2]==6
        f.ack_override=lambda ack:dict(ack,keymap_revision=999)
        await f.event(True,1)
        await f.until(lambda state:state['delegate_transaction']['last_error']=='delegate_keymap_revision_mismatch')
        await f.quiet()
        assert (await f.request({'t':'owner_state'}))['pressed']==1
        await f.event(False);assert await f.report()==bytes(8)


async def ack_source_authorization_and_duplicate():
    async with Fixture([{'0,0':'KC_C','0,1':'LT(1,KC_B)'},{}]) as f:
        await f.event(True);assert (await f.report())[2]==6
        f.ack_override=lambda ack:dict(ack,key_events=[{'id':'unknown','source':999999,'action':'KC_B','is_press':True}])
        await f.event(True,1)
        await f.until(lambda state:state['delegate_transaction']['last_error']=='delegate_source_not_authorized')
        await f.quiet();assert (await f.request({'t':'owner_state'}))['pressed']==1
        await f.event(False);assert await f.report()==bytes(8)
    async with Fixture([{'0,0':'LT(1,KC_B)'},{}]) as f:
        f.duplicate_ack=True
        await f.event(True);await f.event(False)
        assert (await f.report())[2]==5;assert await f.report()==bytes(8)
        await f.until(lambda state:state['idle']);await f.quiet()


async def held_delegated_layer_deleted_by_keymap_apply():
    async with Fixture([{'0,0':'LT(1,KC_B)','0,1':'KC_C'}, {'0,1':'KC_D'}]) as f:
        await f.event(True)
        await f.until(lambda state:state['layer_state']['momentary']==[1] and not state['delegate_transaction']['pending'])
        owner=await f.request({'t':'owner_state'})
        response=await f.request({'t':'apply_keymap','operation_id':'delete-held-layer','layers':[{'0,0':'KC_A','0,1':'KC_E'}],
            'expected_owner_epoch':owner['owner_epoch'],'expected_keymap_revision':owner['keymap_revision']})
        assert response['result']=='ok',response
        await f.event(True,1);assert (await f.report())[2]==8
        await f.event(False,1);assert await f.report()==bytes(8)
        await f.event(False)
        final=await f.until(lambda state:state['idle'])
        assert final['delegate_transaction']['last_error']=='',final


async def sink_backpressure_preserves_control_and_source_cleanup():
    async with Fixture([{'0,0':'KC_C','0,1':'KC_A'}],delegate=False) as f:
        await f.event(True);assert (await f.report())[2]==6
        fillers=[];fill_count=0
        for _ in range(16):
            filler=socket.socket(socket.AF_UNIX,socket.SOCK_DGRAM);filler.setblocking(False);fillers.append(filler)
            before=fill_count
            try:
                while True:filler.sendto(b'fixture-queue-fill',str(f.sink));fill_count+=1
            except BlockingIOError:pass
            if before==fill_count:break  # receiver full, not just one sender's buffer
        else:raise AssertionError('unable to saturate fixture receiver within bounded filler budget')
        source=await f.open_source();await f.event(True,1,source)
        state=await f.request({'t':'owner_state'})
        assert state['output_pending_reports']>0,(state,fill_count)
        source[1].close();await source[1].wait_closed()
        await f.until(lambda state:state['pressed']==1)
        for _ in range(fill_count):
            assert await asyncio.get_running_loop().sock_recv(f.broker,128)==b'fixture-queue-fill'
        for filler in fillers:filler.close()
        report=await f.report();assert 6 in report and 4 not in report, 'obsolete synthetic A must not replay'
        await f.event(False);assert await f.report()==bytes(8)
        await f.until(lambda state:state['output_pending_reports']==0)


async def main():
    for check in (sessions_and_guard,source_revision_and_lease,real_interaction_transactions,stalled_delegate_preserves_native_release,
                  delegated_disconnect_and_delayed_press_cleanup,stale_ack_and_scoped_failure,
                  ack_source_authorization_and_duplicate,sink_backpressure_preserves_control_and_source_cleanup,
                  held_delegated_layer_deleted_by_keymap_apply):
        await check();print(check.__name__+': ok')


if __name__=='__main__':asyncio.run(main())
