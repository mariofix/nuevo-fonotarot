from quart.serving import WsgiToAsgi

from nuevo_fonotarot import create_flask

quart = WsgiToAsgi(create_flask())
