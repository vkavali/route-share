function getApiBase() {
  const raw = process.env.EXPO_PUBLIC_API_URL;
  if (!raw) return null;
  let url;
  try { url = new URL(raw); } catch { throw new Error('EXPO_PUBLIC_API_URL must be an absolute URL.'); }
  const loopback = ['localhost', '127.0.0.1', '::1', '[::1]'].includes(url.hostname.toLowerCase());
  if (url.protocol !== 'https:' && !(loopback && url.protocol === 'http:')) {
    throw new Error('EXPO_PUBLIC_API_URL must use HTTPS except for explicitly configured loopback development hosts.');
  }
  if (url.username || url.password || url.hash || url.search || (url.pathname && url.pathname !== '/')) throw new Error('EXPO_PUBLIC_API_URL must be an API origin without credentials, path or query.');
  return { url, loopback };
}

module.exports = ({ config }) => {
  const api = getApiBase();
  return {
    ...config,
    name: 'SeatPal',
    icon: './assets/seatpal/icon-ios.png',
    slug: 'route-share-mobile',
    version: '0.1.0',
    orientation: 'portrait',
    userInterfaceStyle: 'light',
    newArchEnabled: true,
    platforms: ['ios', 'android'],
    scheme: 'routesharesandbox',
    ios: {
      ...(config.ios || {}),
      bundleIdentifier: 'com.vkavali.routeshare',
      appleTeamId: '722J78K2H6',
      buildNumber: '2',
      supportsTablet: true,
      infoPlist: {
        ...((config.ios && config.ios.infoPlist) || {}),
        CFBundleDisplayName: 'SeatPal',
        ITSAppUsesNonExemptEncryption: false,
        NSLocationWhenInUseUsageDescription: 'Use your location to choose a pickup or destination, or share it with the other participant during an accepted booking. Sharing stops when you stop it or arrive.',
        NSAppTransportSecurity: api?.loopback && api.url.protocol === 'http:'
          ? {NSAllowsArbitraryLoads: false, NSAllowsLocalNetworking: true}
          : {NSAllowsArbitraryLoads: false},
      },
    },
    android: {
      ...(config.android || {}),
      package: 'com.routeshare.beta',
      versionCode: 2,
      adaptiveIcon: {foregroundImage: './assets/seatpal/adaptive-foreground.png', monochromeImage: './assets/seatpal/adaptive-monochrome.png', backgroundColor: '#F6F5F0'},
      permissions: ['ACCESS_COARSE_LOCATION', 'ACCESS_FINE_LOCATION'],
      blockedPermissions: ['ACCESS_BACKGROUND_LOCATION'],
    },
    plugins: [
      ...(config.plugins || []),
      ['expo-splash-screen', {image: './assets/seatpal/splash.png', imageWidth: 120, resizeMode: 'contain', backgroundColor: '#F6F5F0'}],
      ['expo-location', {
        locationWhenInUsePermission: 'Use your location to choose a pickup or destination, or share it with the other participant during an accepted booking. Sharing stops when you stop it or arrive.',
        locationAlwaysAndWhenInUsePermission: false,
        locationAlwaysPermission: false,
        isIosBackgroundLocationEnabled: false,
        isAndroidBackgroundLocationEnabled: false,
        isAndroidForegroundServiceEnabled: false,
      }],
      ['./plugins/withLoopbackCleartext', {enabled: Boolean(api?.loopback && api.url.protocol === 'http:')}],
      ['expo-audio', {
        microphonePermission: 'Record your trip only when you tap the microphone. Audio is temporarily transcribed on the SeatPal server and deleted after processing or cancellation.',
        recordAudioAndroid: true, enableBackgroundRecording: false,
      }],
      'expo-font',
      'expo-secure-store',
    ],
    locales: {
      ...(config.locales || {}),
      en: './locales/en.json',
      te: './locales/te.json',
      hi: './locales/hi.json',
    },
    extra: {
      ...(config.extra || {}),
      androidBundleIdIsPlaceholder: true,
      apiBaseConfigured: Boolean(api),
    },
  };
};
