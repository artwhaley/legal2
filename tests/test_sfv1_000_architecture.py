"""RAUC1 product route inventory."""

from fastapi.routing import APIRoute

from server.app import create_app


def test_sfv1_target_product_routes_are_exactly_four():
    app = create_app()
    routes = {
        (method, route.path)
        for route in app.routes
        if isinstance(route, APIRoute)
        for method in route.methods
        if route.path.startswith("/v1/")
    }
    assert routes == {
        ("POST", "/v1/keyword-expansion"),
        ("POST", "/v1/conversational-plan"),
        ("POST", "/v1/conversational-analysis"),
        ("POST", "/v1/embeddings"),
    }
