from fastapi.testclient import TestClient

from app import main


def test_spa_and_assets_are_served_same_origin_but_unknown_api_stays_404(tmp_path, monkeypatch):
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text('<html><title>RUTEA</title></html>', encoding="utf-8")
    (tmp_path / "assets" / "app.js").write_text("window.RUTEA = true", encoding="utf-8")
    monkeypatch.setattr(main, "FRONTEND_DIST", tmp_path)
    client = TestClient(main.app)

    assert client.get("/").text == '<html><title>RUTEA</title></html>'
    assert client.get("/history").text == '<html><title>RUTEA</title></html>'
    asset = client.get("/assets/app.js")
    assert asset.text == "window.RUTEA = true"
    assert asset.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert client.get("/assets/missing.js").status_code == 404
    assert client.get("/api/v1/not-a-route").status_code == 404
