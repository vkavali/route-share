import * as SplashScreen from 'expo-splash-screen';
// Hold only until a real RN frame (loading, content or recoverable error) lays out.
// Never wait for a network operation, font completion or animation duration.
void SplashScreen.preventAutoHideAsync().catch(()=>{});
let hidden=false;
export function revealNativeFrame(){
 if(hidden)return;
 hidden=true;
 void SplashScreen.hideAsync().catch(()=>{hidden=false;});
}
