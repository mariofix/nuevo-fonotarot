// static/push.js

const csrf = () =>
    document.querySelector('meta[name="csrf-token"]')?.content ?? '';

function urlBase64ToUint8Array(base64) {
  const pad = '='.repeat((4 - base64.length % 4) % 4);
  const raw = atob((base64 + pad).replace(/-/g, '+').replace(/_/g, '/'));
  return Uint8Array.from([...raw].map(c => c.charCodeAt(0)));
}

async function registerPush(retries = 3) {
  if (!('serviceWorker' in navigator) || !('PushManager' in window)) return;

  const permission = await Notification.requestPermission();
  if (permission !== 'granted') return;

  const reg = await navigator.serviceWorker.register('/sw.js');

  await new Promise(resolve => {
    if (reg.active) return resolve();
    const sw = reg.installing || reg.waiting;
    sw.addEventListener('statechange', e => {
      if (e.target.state === 'activated') resolve();
    });
  });

  let sub = await reg.pushManager.getSubscription();
  if (!sub) {
    for (let i = 0; i < retries; i++) {
      try {
        sub = await reg.pushManager.subscribe({
          userVisibleOnly: true,
          applicationServerKey: urlBase64ToUint8Array(_VAPID_PUBLIC_KEY)
        });
        break;
      } catch (e) {
        if (i === retries - 1) throw e;
        await new Promise(r => setTimeout(r, 1000 * (i + 1)));
      }
    }
  }

  console.log('subscription:', JSON.stringify(sub.toJSON()));  // check this

  const response = await fetch(_VAPID_API_SUBSCRIBE, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-CSRFToken': csrf()
    },
    body: JSON.stringify(sub.toJSON())
  });

  console.log('subscribe response:', response.status, response.statusText);

  if (!response.ok) {
    const text = await response.text();
    console.error('subscribe error body:', text);
  }
}

// Call after user interaction (button click or login) — browsers block
// Notification.requestPermission() if called without a user gesture.
document.getElementById('enable-notifications')?.addEventListener('click', registerPush);
