from app.main import app


def test_promotion_rename_route_is_owned_by_current_runtime():
    matches = [
        route for route in app.router.routes
        if getattr(route, 'path', '') == '/promotions/{promotion_id}/name-v030'
        and 'POST' in getattr(route, 'methods', set())
    ]
    assert matches, 'promotion rename POST route is missing'
    assert matches[0].endpoint.__module__ == 'app.v0211_promotion_routes'


if __name__ == '__main__':
    test_promotion_rename_route_is_owned_by_current_runtime()
    print('promotion rename route regression passed')
