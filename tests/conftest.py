import pytest

from nuevo_fonotarot.extensions import db
from nuevo_fonotarot.flask_app import create_flask


@pytest.fixture(scope="session")
def app():
    app = create_flask("testing")
    yield app


@pytest.fixture(autouse=True)
def app_ctx(app):
    with app.app_context():
        db.drop_all()
        db.create_all()
        yield
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app, app_ctx):
    return app.test_client()
