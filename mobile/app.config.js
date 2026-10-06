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
    name: 'Route share · Local beta',
    slug: 'route-share-mobile',
    version: '0.1.0',
    orientation: 'portrait',
    userInterfaceStyle: 'light',
    newArchEnabled: true,
    platforms: ['ios', 'android'],
    scheme: 'routesharesandbox',
    ios: {
      ...(config.ios || {}),
      bundleIdentifier: 'com.routeshare.beta',
      buildNumber: '1',
      supportsTablet: true,
      infoPlist: {
        ...((config.ios && config.ios.infoPlist) || {}),
        NSLocationWhenInUseUsageDescription: 'Share your location with the other participant during this accepted booking. Sharing stops when you stop it or arrive.',
        NSAppTransportSecurity: api?.loopback && api.url.protocol === 'http:'
          ? {NSAllowsArbitraryLoads: false, NSAllowsLocalNetworking: true}
          : {NSAllowsArbitraryLoads: false},
      },
    },
    android: {
      ...(config.android || {}),
      package: 'com.routeshare.beta',
      versionCode: 1,
      permissions: ['ACCESS_COARSE_LOCATION', 'ACCESS_FINE_LOCATION'],
      blockedPermissions: ['ACCESS_BACKGROUND_LOCATION'],
    },
    plugins: [
      ...(config.plugins || []),
      ['expo-location', {
        locationWhenInUsePermission: 'Share your location with the other participant during this accepted booking. Sharing stops when you stop it or arrive.',
        locationAlwaysAndWhenInUsePermission: false,
        locationAlwaysPermission: false,
        isIosBackgroundLocationEnabled: false,
        isAndroidBackgroundLocationEnabled: false,
        isAndroidForegroundServiceEnabled: false,
      }],
      ['./plugins/withLoopbackCleartext', {enabled: Boolean(api?.loopback && api.url.protocol === 'http:')}],
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
      nativeBundleIdsArePlaceholders: true,
      apiBaseConfigured: Boolean(api),
    },
  };
};
