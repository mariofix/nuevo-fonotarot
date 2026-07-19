// static/push.js

const VAPID_PUBLIC_KEY = '{{ config.VAPID_PUBLIC_KEY }}';
const csrf = () =>
    document.querySelector('meta[name="csrf-token"]')?.content ?? '';

const subscribeUrl = () =>
    "{{ url_for(\"api.subscribe\") }}";

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
  await navigator.serviceWorker.ready;

  let sub = await reg.pushManager.getSubscription();
  if (!sub) {
    sub = await reg.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlBase64ToUint8Array(VAPID_PUBLIC_KEY)
    });
  }

  await fetch(subscribeUrl(), {
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
