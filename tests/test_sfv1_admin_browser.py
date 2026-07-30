import socket
import threading
import time

import pytest
import uvicorn

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright

from server.app import create_app
from server.embeddings import EmbeddingService
from tests.sfv1_support import FakeEmbeddingModel, configured_service, fake_provider, server_config


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.mark.browser
def test_admin_real_browser_save_validate_test_and_live_event_poll(tmp_path):
    config = server_config()
    service, _ = configured_service(tmp_path, config)
    app = create_app(config_service=service, provider=fake_provider(), embedding_service=EmbeddingService(config.embedding, model=FakeEmbeddingModel()), embedding_factory=lambda embedding: EmbeddingService(embedding, model=FakeEmbeddingModel(dimensions=embedding.required_dimensions or 3)))
    port = free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_config=None, access_log=False))
    thread = threading.Thread(target=server.run, name="admin-browser-server", daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and thread.is_alive() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert server.started
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(f"http://127.0.0.1:{port}/admin/", wait_until="networkidle")
            assert page.locator("#dashboard").is_visible()
            page.goto(f"http://127.0.0.1:{port}/admin/operations", wait_until="networkidle")
            prompt = page.locator('textarea[name="operation_assignments.keyword_expansion.system_prompt"]')
            original = prompt.input_value()
            prompt.fill(original + "\nAdministrator browser test marker.")
            page.locator('#operation-editor button[value="save_operations"]').click()
            page.wait_for_selector("#notice")
            assert "saved to the draft" in page.locator("#notice").inner_text()
            page.locator('button[value="validate"]').first.click()
            page.wait_for_selector("#notice")
            assert "Draft is valid" in page.locator("#notice").inner_text()
            page.goto(f"http://127.0.0.1:{port}/admin/activity", wait_until="networkidle")
            page.locator('select[name="operation"]').nth(0).select_option("keyword_expansion")
            page.locator('button[value="test"]').click()
            page.wait_for_selector("#test-output")
            assert '"schema_valid": true' in page.locator("#test-output").inner_text()
            page.goto(f"http://127.0.0.1:{port}/admin/", wait_until="networkidle")
            app.state.events.emit("browser_poll_proof")
            page.wait_for_function("document.querySelector('#metrics').textContent.includes('browser_poll_proof')", timeout=7_000)
            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=15)
        assert not thread.is_alive()
