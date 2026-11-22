'use strict';
// The combined display already has navigation; avoid nesting it inside itself.
document.querySelector('nav').hidden = window.self !== window.top;
// Fixed local endpoints only. No camera credentials or direct camera URLs.
for (const name of ['fillcam0', 'fillcam1', 'fillcam2']) {
  const panel = document.createElement('section');
  const heading = document.createElement('h2');
  heading.textContent = `Fill camera ${name.slice(-1)}`;
  const video = document.createElement('video');
  video.muted = true;
  video.autoplay = true;
  video.playsInline = true;
  video.controls = true;
  const status = document.createElement('p');
  status.className = 'status';
  status.setAttribute('role', 'status');
  const retry = document.createElement('button');
  retry.textContent = 'Retry camera';
  let timer;
  let watchdog;
  const fail = () => {
    clearTimeout(watchdog);
    clearTimeout(timer);
    status.textContent = 'Camera unavailable or playback stalled. Retrying in 5 seconds.';
    timer = setTimeout(connect, 5000);
  };
  const connect = () => {
    clearTimeout(timer);
    clearTimeout(watchdog);
    status.textContent = 'Connecting…';
    video.src = `/cameras/${name}/stream.mp4`;
    video.load();
    // A missing or stalled source must not leave an indefinite "connecting" state.
    watchdog = setTimeout(fail, 20000);
    video.play().catch(() => {
      status.textContent = 'Playback unavailable or blocked. Use Play or Retry camera.';
    });
  };
  video.addEventListener('error', fail);
  video.addEventListener('ended', fail);
  video.addEventListener('timeupdate', () => {
    if (video.paused) return;
    clearTimeout(watchdog);
    clearTimeout(timer);
    status.textContent = 'Receiving video';
    watchdog = setTimeout(fail, 20000);
  });
  retry.addEventListener('click', connect);
  panel.append(heading, video, status, retry);
  document.getElementById('cameras').append(panel);
  connect();
}
