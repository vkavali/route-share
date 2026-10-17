import * as SplashScreen from 'expo-splash-screen';
// Hold until the first real RN layout has had two paint opportunities.
// Never wait for network, fonts, auth or an animation duration.
void SplashScreen.preventAutoHideAsync().catch(()=>{});
let hidden=false;
let revealScheduled=false;
export function revealNativeFrame(){
 if(hidden||revealScheduled)return;
 revealScheduled=true;
 requestAnimationFrame(()=>{
  requestAnimationFrame(()=>{
   revealScheduled=false;
   if(hidden)return;
   hidden=true;
   void SplashScreen.hideAsync().catch(()=>{hidden=false;});
  });
 });
}
