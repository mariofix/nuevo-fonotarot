// /sw.js
self.addEventListener('push', event => {
  if (!event.data) return;
  const data = event.data.json();
  event.waitUntil(
    self.registration.showNotification(data.title, {
      body: data.body,
      icon: '/static/favicon-32.png',
      badge: '/static/og-image.png',
      requireInteraction: true,
      data: {
        url: data.url,
        phone: data.phone,
        call_url: data.call_url
      },
      actions: [
        { action: 'call', title: 'Llamar Ahora!' },
        { action: 'dismiss', title: 'Dismiss' }
      ]
    })
  );
});

self.addEventListener('notificationclick', event => {
  event.notification.close();
  const { url, phone, call_url } = event.notification.data;

  if (event.action === 'call') {
    const target = phone ? 'tel:' + phone : call_url;
    event.waitUntil(clients.openWindow(target));
    return;
  }

  if (event.action === 'dismiss') return;

  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then(list => {
      for (const client of list) {
        if (client.url === url && 'focus' in client) return client.focus();
      }
      return clients.openWindow(url);
    })
  );
});
