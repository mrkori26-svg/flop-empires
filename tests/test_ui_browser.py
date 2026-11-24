import secrets
import shutil
import threading
from http.server import ThreadingHTTPServer

import pytest
from playwright.sync_api import expect, sync_playwright

from flop_empires import ui_server
from flop_empires.store import Store


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        yield browser
        browser.close()


@pytest.fixture
def ui(tmp_path, monkeypatch):
    db = tmp_path / "ui.sqlite3"
    store = Store(db)
    store.conn.execute("INSERT INTO config(key, value) VALUES ('season_status', 'REGISTRATION')")
    store.close()
    monkeypatch.setattr(ui_server, "DEFAULT_DB", db)
    with ThreadingHTTPServer(("127.0.0.1", 0), ui_server.Handler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"http://127.0.0.1:{server.server_port}"
        finally:
            server.shutdown()
            thread.join()


@pytest.mark.parametrize("recovery", [False, True], ids=["original", "recovery"])
def test_public_dashboard(browser, ui, recovery, tmp_path, monkeypatch):
    if not recovery:
        activation = tmp_path / ui_server.ACTIVATION.name
        shutil.copyfile(ui_server.ACTIVATION, activation)
        monkeypatch.setattr(ui_server, "ACTIVATION", activation)
        monkeypatch.setattr(ui_server, "RECOVERY", tmp_path / ui_server.RECOVERY.name)

    with browser.new_context() as context:
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(ui)
        state = page.request.get(ui + "/api/state").json()
        proof = page.locator("#proofCard")
        expect(proof.locator("h3")).to_have_text(state["evidence"]["projection_schema"])
        if recovery:
            record = state["season"]["recovery"]
            expect(proof).to_contain_text(record["recovery_id"])
            expect(proof.locator("a.proof-link")).to_have_attribute("href", record["evidence_url"])
        else:
            expect(proof.locator("a")).to_have_count(0)
        expect(page.locator("#identityStatus")).to_contain_text("Observer mode")
        expect(page.locator("#worldMap .territory")).to_have_count(len(state["world"]["territories"]))
        phase = page.locator("#heroStats .stat").filter(has=page.get_by_text("Phase", exact=True))
        expect(phase.locator("strong")).to_have_text(state["season"]["status"])
        expect(phase.locator("small")).to_have_text("Launch authorization required")
        assert not errors


def test_seed_session_through_ui(browser, ui):
    with browser.new_context() as context:
        page = context.new_page()
        page.goto(ui)
        page.locator("#identityButton").click()
        page.locator(".seed-import summary").click()
        page.locator("#seedInput").fill(secrets.token_hex(32))
        page.locator("#useSeed").click()
        identity = page.locator("#identityStatus")
        expect(identity).to_contain_text("Signing key loaded in memory")
        viewer = page.request.get(ui + "/api/state").json()["viewer"]
        assert viewer["authenticated"]
        expect(identity).to_contain_text(viewer["did"])
        page.reload()
        page.locator("#identityButton").click()
        expect(identity).to_contain_text("Session valid")
        expect(identity).to_contain_text(viewer["did"])
        page.locator("#logoutIdentity").click()
        expect(identity).to_contain_text("Observer mode")
        assert not page.request.get(ui + "/api/state").json()["viewer"]["authenticated"]
