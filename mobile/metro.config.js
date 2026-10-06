const { getDefaultConfig } = require('expo/metro-config');

const config = getDefaultConfig(__dirname);
// CI builds must not depend on a shared interactive Watchman daemon.
if (process.env.CI === '1') config.resolver.useWatchman = false;
module.exports = config;
