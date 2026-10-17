import { mountSeatPalStartupMotion } from './seatpal-startup-renderer.js';

const stage = document.querySelector('[data-seatpal-startup]');
const slider = document.querySelector('.preview-slider');
const status = document.querySelector('[data-preview-status]');
const phases = [...document.querySelectorAll('[data-seek]')];
const phaseNames = ['Start', 'Car', 'Bike', 'Resolve', 'Logo'];
let lastPhase = null;
const updatePreview = progress => {
  slider.value = String(Math.round(progress * 1000));
  const phaseIndex = progress < .20 ? 0 : progress < .50 ? 1 : progress < .80 ? 2 : progress < .97 ? 3 : 4;
  if (phaseIndex !== lastPhase) {
    lastPhase = phaseIndex;
    status.textContent = `Animation preview: ${phaseNames[phaseIndex]} phase`;
  }
};
const controller = mountSeatPalStartupMotion(stage, { autoStart: true, onFrame: updatePreview });
slider.addEventListener('input', () => {
  controller.seek(Number(slider.value) / 1000);
});
phases.forEach(button => button.addEventListener('click', () => {
  const value = Number(button.dataset.seek);
  slider.value = String(Math.round(value * 1000));
  controller.seek(value);
  status.textContent = `Animation preview: ${button.textContent} phase`;
}));
document.querySelector('[data-replay]').addEventListener('click', () => {
  slider.value = '0';
  lastPhase = null;
  status.textContent = 'Animation preview: Start phase';
  controller.replay();
});
controller.ready.then(ready => {
  if (!ready) status.textContent = 'Animation preview unavailable';
});
