// static/push.js

const csrf = () =>
    document.querySelector('meta[name="csrf-token"]')?.content ?? '';

function urlBase64ToUint8Array(base64) {
  const pad = '='.repeat((4 - base64.length % 4) % 4);
  const raw = atob((base64 + pad).replace(/-/g, '+').replace(/_/g, '/'));
  return Uint8Array.from([...raw].map(c => c.charCodeAt(0)));
}

async function registerPush() {
  if (!('serviceWorker' in navigator) || !('PushManager' in window)) return;

  const permission = await Notification.requestPermission();
  if (permission !== 'granted') return;

  const reg = await navigator.serviceWorker.register('/sw.js');

  // Wait for THIS registration to be active, not just any SW
  await new Promise(resolve => {
    if (reg.active) return resolve();
    const sw = reg.installing || reg.waiting;
    sw.addEventListener('statechange', e => {
      if (e.target.state === 'activated') resolve();
    });
  });

  let sub = await reg.pushManager.getSubscription();
  if (!sub) {
    sub = await reg.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlBase64ToUint8Array(_VAPID_PUBLIC_KEY)
    });
  }

  await fetch(_VAPID_API_SUBSCRIBE, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-CSRFToken': csrf()
    },
    body: JSON.stringify(sub.toJSON())
  });
}

// Call after user interaction (button click or login) — browsers block
// Notification.requestPermission() if called without a user gesture.
document.getElementById('enable-notifications')?.addEventListener('click', registerPush);
