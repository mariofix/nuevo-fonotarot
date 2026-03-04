from quart.serving import WsgiToAsgi

from nuevo_fonotarot import create_flask

app = WsgiToAsgi(create_flask())
