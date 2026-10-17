// Generated from the approved SeatPal landing motion. Pure frame calculation; no DOM or timing side effects.
export const STARTUP_MS = 3600;
export const STARTUP_ASSET_HASH = '7ec72ea113f6425071aa22ad91c2377f8b7247e1c6ee16cc33b03e356ca5a37a';
export const VIEW_BOX = Object.freeze({ x: 120, y: 130, width: 740, height: 310 });
const LOGO_VIEW_BOX = Object.freeze({ x: 285, y: 183, width: 430, height: 430 * 310 / 740 });
const clamp = (x) => Math.min(1, Math.max(0, x));
const ease = (x) => { x = clamp(x); return x * x * x * (x * (x * 6 - 15) + 10); };
const phase = (t, a, b) => ease((t - a) / (b - a));
const mix = (a, b, p) => a + (b - a) * p;

export function frameAt(progress) {
  const p = clamp(Number(progress) || 0);
  const intoCar = phase(p, .08, .28), toBike = phase(p, .38, .61), resolve = phase(p, .69, .89);
  const openingCamera = phase(p, .08, .28);
  const carBuild = phase(p, .12, .29), carLineRetract = phase(p, .36, .48);
  const carFillBuild = phase(p, .22, .32), carFillRetract = phase(p, .36, .43);
  const bikeBuild = phase(p, .48, .64), bikeRetract = phase(p, .73, .91);
  const bikeFillBuild = phase(p, .55, .64);
  let seatX = mix(466, 328, intoCar), seatY = mix(307, 326, intoCar), seatScale = mix(1.1, .76, intoCar);
  seatX = mix(seatX, 410, toBike); seatY = mix(seatY, 282, toBike); seatScale = mix(seatScale, .52, toBike);
  seatX = mix(seatX, 315, resolve); seatY = mix(seatY, 306, resolve); seatScale = mix(seatScale, .54, resolve);
  const fold = toBike * (1 - resolve);
  const backBase = mix(mix(-8, -12, intoCar), -8, resolve);
  const backAngle = mix(backBase, -88, fold);
  const backScaleX = mix(1, .55, fold);
  const carLineProgress = carBuild * (1 - carLineRetract);
  const carFillOpacity = carFillBuild * (1 - carFillRetract);
  const driverOpacity = phase(p, .24, .32) * (1 - phase(p, .36, .45));
  const carOpacity = carLineProgress;
  const bikeLineProgress = bikeBuild * (1 - bikeRetract);
  const bikeFillOpacity = bikeFillBuild * (1 - bikeRetract);
  const bikeOpacity = bikeLineProgress;
  const bikeDecorationOpacity = bikeBuild * (1 - bikeRetract);
  const bikeRearDetailsOpacity = bikeBuild * (1 - bikeRetract);
  const tankOpacity = bikeFillBuild * (1 - phase(p, .69, .77));
  const engineOpacity = bikeFillBuild * (1 - phase(p, .69, .77));
  const wheelTransfer = phase(p, .44, .61);
  let rearX = mix(260, 365, wheelTransfer), frontX = mix(700, 585, wheelTransfer);
  const rearStart = rearX, frontStart = frontX;
  const collect = phase(p, .70, .89), targetX = seatX, targetY = seatY + 3 * seatScale;
  const bikeLift = 22 * Math.sin(Math.PI * collect), bikeKeep = 1 - collect;
  rearX = mix(rearX, targetX, collect); frontX = mix(frontX, targetX, collect);
  const wheelY = mix(365, targetY, collect) + bikeLift;
  const wheelScale = Math.pow(1 - collect, 1.4) + .035 * collect;
  const words = phase(p, .79, .95);
  const camera = phase(p, .80, .96);
  const viewWidth = mix(VIEW_BOX.width, LOGO_VIEW_BOX.width, camera);
  const view = {
    viewBoxX: mix(mix(127, VIEW_BOX.x, openingCamera), LOGO_VIEW_BOX.x, camera),
    viewBoxY: mix(mix(88, VIEW_BOX.y, openingCamera), LOGO_VIEW_BOX.y, camera),
    viewBoxWidth: viewWidth,
    viewBoxHeight: viewWidth * VIEW_BOX.height / VIEW_BOX.width,
  };
  return {
    seatX, seatY, seatScale, backAngle, backScaleX,
    railOpacity: 1 - fold,
    carOpacity, carLineProgress, carFillOpacity, carDecorationOpacity: carFillOpacity,
    carSmallDetailsOpacity: carFillOpacity, driverOpacity, carX: 0, carScaleX: 1,
    bikeOpacity, bikeLineProgress, bikeFillOpacity, bikeDecorationOpacity, bikeRearDetailsOpacity, tankOpacity, engineOpacity,
    bikeX: targetX * collect, bikeY: targetY * collect + bikeLift, bikeScale: bikeKeep,
    rearX, frontX, wheelY, wheelScale,
    wheelOpacity: 1 - phase(p, .89, .94),
    rearRotation: (rearX - 260) / 52.5 * 180 / Math.PI,
    frontRotation: (frontX - 700) / 52.5 * 180 / Math.PI,
    wordOpacity: words, wordReveal: words, wordX: 10 * (1 - words), ...view,
  };
}

export const STARTUP_FRAME0_SVG = "<svg xmlns:ns0=\"http://www.w3.org/2000/svg\" xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"127 88 740 310\" width=\"100%\" height=\"100%\" focusable=\"false\" aria-hidden=\"true\" data-seatpal-frame=\"0\"><g transform=\"translate(466 307) scale(1.1)\"><g transform=\"rotate(-8)\"><ns0:g id=\"sp-seatpal-seat-back\">\n      <ns0:path d=\"M-8-122V-109M6-122V-109\" stroke=\"#778591\" stroke-width=\"3.5\" stroke-linecap=\"round\" />\n      <ns0:path d=\"M-17-136Q-17-143-10-143H7Q15-143 15-136V-125Q15-118 8-118H-10Q-17-118-17-125Z\" fill=\"#FF7A24\" />\n      <ns0:path d=\"M-19-101Q-20-115-7-116H7Q18-115 20-101L18-31Q18-15 5-6L-7-5Q-18-10-19-25Z\" fill=\"#26323c\" />\n      <ns0:path d=\"M-8-105H3Q9-105 9-98L7-37Q7-25 1-20\" fill=\"none\" stroke=\"#9eabb5\" stroke-width=\"2.5\" stroke-linecap=\"round\" />\n    </ns0:g></g><g><ns0:path id=\"sp-seatpal-seat-rail\" d=\"M-5 27H77\" fill=\"none\" stroke=\"#9aa7b2\" stroke-width=\"4\" stroke-linecap=\"round\" /></g><g><ns0:g><ns0:path id=\"sp-seatpal-cushion\" d=\"M-14-4Q-10-12 1-12H69Q84-12 91-3L96 5Q99 18 86 18H-6Q-19 18-19 7Z\" fill=\"#26323c\" /><ns0:path d=\"M-5-2H68Q81-2 85 5\" fill=\"none\" stroke=\"#9eabb5\" stroke-width=\"2.5\" stroke-linecap=\"round\" /><ns0:circle id=\"sp-seatpal-hinge\" cx=\"0\" cy=\"3\" r=\"5\" fill=\"#FF7A24\" /></ns0:g></g></g></svg>";
