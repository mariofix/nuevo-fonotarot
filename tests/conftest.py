import pytest

from nuevo_fonotarot.extensions import db
from nuevo_fonotarot.flask_app import create_flask


@pytest.fixture(scope="session")
def app():
    app = create_flask("testing")
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()
