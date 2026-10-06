import React, {createContext, useContext, useState} from 'react';
import {ActivityIndicator, Pressable, StyleSheet, Text as NativeText, View} from 'react-native';
import {useFonts} from 'expo-font';
import {T} from './translation';

const fontAssets = {
  Manrope400: require('../assets/fonts/Manrope-400.ttf'),
  Manrope500: require('../assets/fonts/Manrope-500.ttf'),
  Manrope600: require('../assets/fonts/Manrope-600.ttf'),
  Manrope700: require('../assets/fonts/Manrope-700.ttf'),
  AnekTelugu400: require('../assets/fonts/AnekTelugu-400.ttf'),
  AnekTelugu500: require('../assets/fonts/AnekTelugu-500.ttf'),
  AnekTelugu600: require('../assets/fonts/AnekTelugu-600.ttf'),
  AnekTelugu700: require('../assets/fonts/AnekTelugu-700.ttf'),
};

const LanguageContext = createContext('en');

export function NativeTypographyProvider({lang, children}: {lang: string; children: React.ReactNode}) {
  const [attempt, setAttempt] = useState(0);
  return <FontLoader key={attempt} lang={lang} onRetry={() => setAttempt(value => value + 1)}>{children}</FontLoader>;
}

function FontLoader({lang, children, onRetry}: {lang: string; children: React.ReactNode; onRetry: () => void}) {
  const [loaded, error] = useFonts(fontAssets);
  if (error) {
    return <View style={styles.failure}>
      <NativeText style={styles.failureText}>{T(lang, 'fontLoadError')}</NativeText>
      <Pressable accessibilityRole="button" onPress={onRetry} style={styles.retry}>
        <NativeText style={styles.retryText}>{T(lang, 'retry')}</NativeText>
      </Pressable>
    </View>;
  }
  if (!loaded) {
    return <View style={styles.loading}><ActivityIndicator color="#153C32" size="large" /></View>;
  }
  return <LanguageContext.Provider value={lang}>{children}</LanguageContext.Provider>;
}

export function AppText({style, lang: scriptLang, ...props}: React.ComponentProps<typeof NativeText> & {lang?: string}) {
  const contextLang = useContext(LanguageContext);
  const lang = scriptLang || contextLang;
  const textStyle = StyleSheet.flatten(style) || {};
  const requested = String(textStyle.fontWeight || '500');
  const weight = requested === '500' || requested === '600' || requested === '700'
    ? requested
    : requested === 'bold' || requested === '800' || requested === '900' ? '700' : '400';
  const family = textStyle.fontFamily || `${lang === 'te' ? 'AnekTelugu' : 'Manrope'}${weight}`;
  const teluguLineHeight = lang === 'te' && !textStyle.lineHeight
    ? Math.round(Number(textStyle.fontSize || 16) * 1.48)
    : undefined;

  return <NativeText {...props} style={[style, {fontFamily: family, fontWeight: 'normal', lineHeight: textStyle.lineHeight || teluguLineHeight, letterSpacing: lang === 'te' ? 0 : textStyle.letterSpacing}]} />;
}

const styles = StyleSheet.create({
  loading: {flex: 1, alignItems: 'center', justifyContent: 'center', backgroundColor: '#F5F4EC'},
  failure: {flex: 1, alignItems: 'center', justifyContent: 'center', gap: 16, padding: 24, backgroundColor: '#F5F4EC'},
  failureText: {maxWidth: 330, textAlign: 'center', color: '#153C32', fontSize: 16, lineHeight: 25},
  retry: {minHeight: 46, justifyContent: 'center', paddingHorizontal: 20, borderRadius: 14, backgroundColor: '#153C32'},
  retryText: {color: '#fff', fontSize: 15, fontWeight: '700'},
});
