"""Wrapper REST di HeartMuLa: stesso contratto di ACE-Step, provato con il vero AceStepClient e un finto modello."""

import os
import time
from pathlib import Path

import aiohttp
import pytest
from aiohttp.test_utils import TestServer

import heartmula_server as hm
from cogs.ace_step_cog import AceStepClient, AceStepConfig, AceStepError

AUDIO = b"RIFF" + b"\x02" * 500


@pytest.fixture
async def wrapper(tmp_path, monkeypatch):
    monkeypatch.setattr(hm, "OUT_DIR", tmp_path / "out")
    calls = []

    def fake_run(pipe, job):
        calls.append(job)
        if job["lyrics"] == "boom":
            raise RuntimeError("OOM")
        path = hm.OUT_DIR / f"{job['id']}.wav"
        path.write_bytes(AUDIO)
        return str(path)

    server = TestServer(hm.make_app(load=lambda: "pipe", run=fake_run))
    await server.start_server()
    session = aiohttp.ClientSession()
    url = str(server.make_url("")).rstrip("/")
    client = AceStepClient(AceStepConfig(base_url=url, poll_interval=0.01, timeout=5), session)
    yield type("W", (), {"client": client, "url": url, "calls": calls, "session": session})
    await session.close()
    await server.close()


async def test_the_bots_client_works_unchanged_against_the_wrapper(wrapper):
    assert await wrapper.client.health() is True
    task_id, position = await wrapper.client.submit(
        "Western ballad, fingerpicked guitar", "[Verse]\nuno due tre", 45, "it", None, "heartmula")
    assert position is not None
    details = await wrapper.client.wait_for_result(task_id)
    assert details["metas"]["duration"] == 45
    assert await wrapper.client.download(details["file"], max_bytes=10_000) == AUDIO
    job = wrapper.calls[0]
    assert (job["caption"], job["lyrics"], job["duration"]) == ("Western ballad, fingerpicked guitar", "[Verse]\nuno due tre", 45)


async def test_each_job_gets_its_own_seed_and_runs_one_at_a_time(wrapper):
    ids = [(await wrapper.client.submit("jazz", "[Verse]\na b c", 30, "it", None, "heartmula"))[0] for _ in range(3)]
    for task_id in ids:
        await wrapper.client.wait_for_result(task_id)
    assert len({job["seed"] for job in wrapper.calls}) == 3 and len(wrapper.calls) == 3


async def test_a_failed_generation_is_reported_as_failed(wrapper):
    task_id, _ = await wrapper.client.submit("jazz", "boom", 30, "it", None, "heartmula")
    with pytest.raises(AceStepError, match="fallita"):
        await wrapper.client.wait_for_result(task_id)


@pytest.mark.parametrize("body", [
    {}, {"prompt": "jazz"}, {"prompt": "", "lyrics": "x y"}, {"prompt": "jazz", "lyrics": "  "},
    {"prompt": "jazz", "lyrics": "x", "audio_duration": 5}, {"prompt": "jazz", "lyrics": "x", "audio_duration": "boh"},
])
async def test_invalid_requests_are_rejected(wrapper, body):
    async with wrapper.session.post(f"{wrapper.url}/release_task", json=body) as response:
        assert (await response.json())["code"] == 400


async def test_audio_endpoint_never_serves_files_outside_the_output_folder(wrapper, tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("x")
    for path in (str(secret), "/etc/passwd", "../../etc/passwd", ""):
        async with wrapper.session.get(f"{wrapper.url}/v1/audio", params={"path": path}) as response:
            assert response.status == 403, path


def test_caption_becomes_comma_separated_tags_without_spaces():
    assert hm.tags_from_caption("Western ballad,  fingerpicked guitar ,\nharmonica, ") == "Western ballad,fingerpicked guitar,harmonica"


async def test_old_songs_are_deleted_when_a_new_job_arrives(wrapper):
    old = hm.OUT_DIR / "vecchio.wav"
    old.write_bytes(b"x")
    os.utime(old, (time.time() - 2 * hm.KEEP_SECONDS,) * 2)
    await wrapper.client.submit("jazz", "[Verse]\na b c", 30, "it", None, "heartmula")
    assert not old.exists()
