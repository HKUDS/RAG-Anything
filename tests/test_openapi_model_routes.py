"""Route-registration smoke coverage for catalog and KB vision endpoints."""


def test_model_and_vision_routes_are_in_openapi_schema():
    # Importing the app constructs routers but does not run the lifespan, so
    # this remains a deployment-safe smoke test without a PostgreSQL service.
    from server import app

    paths = app.openapi()["paths"]

    assert "/api/model-profiles" in paths
    assert "/api/admin/model-profiles/{profile_id}/probe" in paths
    assert "/api/vision-models" in paths
    assert "/api/kb/{kb}/vision-settings" in paths
    assert {"get", "put"}.issubset(paths["/api/kb/{kb}/vision-settings"])
