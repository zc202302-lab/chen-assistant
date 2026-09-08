from app.main import app


CURRENT_MODULE = 'app.v0211_promotion_routes'


def current_route(path: str, method: str):
    matches = [
        route for route in app.router.routes
        if getattr(route, 'path', '') == path
        and method in getattr(route, 'methods', set())
    ]
    assert matches, f'{method} {path} route is missing'
    assert matches[0].endpoint.__module__ == CURRENT_MODULE


def test_promotion_routes_are_owned_by_current_runtime():
    current_route('/promotions/{promotion_id}/name-v030', 'POST')
    current_route('/services/{service_id}/promotions-editor-v029', 'GET')
    current_route('/services/{service_id}/promotions-editor-v029', 'POST')
    current_route('/promotions/{promotion_id}/close-editor-v029', 'POST')


if __name__ == '__main__':
    test_promotion_routes_are_owned_by_current_runtime()
    print('bidirectional promotion route regression passed')
