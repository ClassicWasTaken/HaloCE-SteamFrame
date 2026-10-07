"""Build source artifacts cannot replace their repository-pinned checksums."""
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def notices():
    spec = importlib.util.spec_from_file_location("pinned_notice_sources", ROOT / "scripts/gather_notices.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_substituted_source_is_refused_before_writing_any_notice(tmp_path, monkeypatch):
    module = notices()
    downloads = []
    def fetch(url, *args):
        downloads.append(url)
        # Remote metadata could advertise this archive and a matching digest;
        # the expected value comes only from the separately reviewed source pin.
        return b"substituted source archive"
    monkeypatch.setattr(module, "get_https", fetch)
    with pytest.raises(RuntimeError, match="checksum mismatch"):
        module.download_sources(tmp_path, [{"name": "paramiko", "version": "4.0.0"}])
    assert downloads == [module.PARAMIKO_SOURCE_URL]
    assert not list(tmp_path.iterdir())


def test_dependency_upgrade_requires_review_before_any_network_fetch(tmp_path, monkeypatch):
    module = notices()
    def no_fetch(*args):
        raise AssertionError("Unreviewed dependency must not initiate a download")
    monkeypatch.setattr(module, "get_https", no_fetch)
    with pytest.raises(RuntimeError, match="repository-pinned Paramiko"):
        module.download_sources(tmp_path, [{"name": "paramiko", "version": "future-unreviewed"}])
    assert not list(tmp_path.iterdir())
