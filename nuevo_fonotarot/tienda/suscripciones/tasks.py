"""Subscription renewal tasks — to be implemented.

Intended flow:
  1. A scheduler (e.g. APScheduler or a cron endpoint) calls
     create_renewal_orders() at the configured billing interval.
  2. create_renewal_orders() finds all active subscriptions due for
     renewal, creates an Order + OrderItem for each, and calls
     send_payment_links() to email the payment URL to the subscriber.
  3. The subscriber clicks the link, which hits suscripciones.iniciar_pago,
     which calls create_payment_and_redirect() from tienda.utils.
"""
