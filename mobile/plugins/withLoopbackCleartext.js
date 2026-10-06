const {withAndroidManifest} = require('@expo/config-plugins');

module.exports = function withLoopbackCleartext(config, options = {}) {
  return withAndroidManifest(config, mod => {
    const application = mod.modResults.manifest.application?.[0];
    if (!application) throw new Error('Android application manifest is missing.');
    if (options.enabled === true) {
      application.$ = application.$ || {};
      application.$['android:usesCleartextTraffic'] = 'true';
    } else if (application.$) {
      delete application.$['android:usesCleartextTraffic'];
    }
    return mod;
  });
};
