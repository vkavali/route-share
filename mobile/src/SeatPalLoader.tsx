import React,{useEffect,useRef,useState} from 'react';
import {AccessibilityInfo,Animated,AppState,Easing,StyleSheet,Text,View,type StyleProp,type ViewStyle} from 'react-native';
import Svg,{G,SvgXml} from 'react-native-svg';
import {seatPalArt,seatPalColors} from './SeatPalArt';
const AnimatedGroup=Animated.createAnimatedComponent(G);
const STARTUP_MS=4400;
// Shared across font/auth boundaries and retries. Decoration never gates readiness.
let startupStartedAt:number|null=null;
const startupFraction=()=>Math.min(1,Math.max(0,(Date.now()-(startupStartedAt??Date.now()))/STARTUP_MS));
type Props={label:string;variant?:'compact'|'startup';fontFamily?:string;style?:StyleProp<ViewStyle>};
export function SeatPalLoader({label,variant='compact',fontFamily,style}:Props){
 if(variant==='startup'&&startupStartedAt===null)startupStartedAt=Date.now();
 const [reduceMotion,setReduceMotion]=useState(true),[foreground,setForeground]=useState(AppState.currentState==='active');
 const compactStartedAt=useRef(Date.now());
 const progress=useRef(new Animated.Value(variant==='startup'?startupFraction():0)).current;
 const waiting=useRef(new Animated.Value(0)).current;
 const running=useRef<Animated.CompositeAnimation|null>(null);
 useEffect(()=>{
  let alive=true,preferenceChanged=false;
  const preference=AccessibilityInfo.addEventListener('reduceMotionChanged',value=>{preferenceChanged=true;if(value)running.current?.stop();setReduceMotion(value);});
  void AccessibilityInfo.isReduceMotionEnabled().then(value=>{if(alive&&!preferenceChanged)setReduceMotion(value);}).catch(()=>{});
  const appState=AppState.addEventListener('change',state=>{if(state!=='active')running.current?.stop();setForeground(state==='active');});
  return()=>{alive=false;preference.remove();appState.remove();running.current?.stop();};
 },[]);
 useEffect(()=>{
  running.current?.stop();
  const fraction=variant==='startup'?startupFraction():Math.min(1,Math.max(0,(Date.now()-compactStartedAt.current)/STARTUP_MS));
  progress.setValue(fraction);waiting.setValue(0);
  if(reduceMotion||!foreground)return;
  let active=true;
  const pulse=()=>{
   if(!active||variant!=='compact')return;
   const animation=Animated.loop(Animated.timing(waiting,{toValue:1,duration:1800,easing:Easing.linear,useNativeDriver:true,isInteraction:false}));
   running.current=animation;animation.start();
  };
  if(fraction>=1)pulse();
  else{
   const animation=Animated.timing(progress,{toValue:1,duration:STARTUP_MS*(1-fraction),easing:Easing.linear,useNativeDriver:false,isInteraction:false});
   running.current=animation;animation.start(({finished})=>{if(finished)pulse();});
  }
  return()=>{active=false;running.current?.stop();running.current=null;};
 },[reduceMotion,foreground,variant,progress,waiting]);
 const motion=!reduceMotion&&foreground;
 const interpolate=(range:number[],values:number[])=>progress.interpolate({inputRange:range,outputRange:values,extrapolate:'clamp'});
 const markOpacity=motion?interpolate([0,.08,.16,.88,1],[1,1,0,0,1]):1;
 const pulse=motion&&variant==='compact'?waiting.interpolate({inputRange:[0,.5,1],outputRange:[1,1.055,1]}):1;
 const art=(name:keyof typeof seatPalArt)=><SvgXml xml={seatPalArt[name]} width={520} height={300}/>;
 return <View testID={`seatpal-loader-${variant}`} accessible accessibilityRole="progressbar" accessibilityLabel={label} accessibilityState={{busy:true}} accessibilityLiveRegion="polite" style={[variant==='startup'?styles.startup:styles.compact,style]}>
  <View importantForAccessibility="no-hide-descendants" accessibilityElementsHidden style={variant==='startup'?styles.stage:styles.smallStage}>
   <Animated.View style={[variant==='startup'?styles.seat:styles.smallSeat,{opacity:markOpacity,transform:[{scale:pulse}]}]}><SvgXml xml={seatPalArt.mark} width={variant==='startup'?120:44} height={variant==='startup'?120:44}/></Animated.View>
   {motion?<Svg style={variant==='startup'?styles.vehicle:styles.smallVehicle} width={variant==='startup'?280:44} height={variant==='startup'?162:44} viewBox="0 0 520 300">
    <AnimatedGroup opacity={interpolate([0,.16,.24,.43,.54,1],[0,0,1,1,0,0])}>{art('car')}</AnimatedGroup>
    <AnimatedGroup opacity={interpolate([0,.49,.58,.77,.88,1],[0,0,1,1,0,0])}>{art('motorcycle')}</AnimatedGroup>
    <AnimatedGroup fill={seatPalColors.forest} opacity={interpolate([0,.08,.16,.88,1],[0,0,1,1,0])}>
     <AnimatedGroup originX={216} originY={181} rotation={interpolate([0,.43,.58,.77,.88,1],[0,0,-72,-72,0,0])} scaleX={interpolate([0,.43,.58,.77,.88,1],[1,1,.3,.3,1,1])} scaleY={interpolate([0,.16,.24,.43,.58,.77,.88,1],[1,1,.55,.55,.3,.3,1,1])}>
      {art('backrest')}<AnimatedGroup opacity={interpolate([0,.43,.58,.77,.88,1],[1,1,0,0,1,1])}>{art('headrest')}</AnimatedGroup>
     </AnimatedGroup>
     <AnimatedGroup originX={216} originY={181} scaleY={interpolate([0,.43,.58,.77,.88,1],[1,1,.45,.45,1,1])}>{art('base')}</AnimatedGroup>
     {art('cushion')}
    </AnimatedGroup>
   </Svg>:null}
  </View>
  <View style={variant==='startup'?styles.startupCaption:styles.caption} accessible={false}>{variant==='startup'?<Text style={styles.brand}>SeatPal</Text>:null}<Text style={[styles.label,fontFamily?{fontFamily}:null]}>{label}</Text></View>
 </View>;
}
const styles=StyleSheet.create({
 startup:{flex:1,width:'100%',alignItems:'center',justifyContent:'center',backgroundColor:seatPalColors.ivory,minHeight:280},
 compact:{alignItems:'center',justifyContent:'center',gap:12,padding:18,borderRadius:20,backgroundColor:seatPalColors.ivory,maxWidth:300},
 stage:{width:280,height:180},smallStage:{width:44,height:44,flexShrink:0},seat:{position:'absolute',width:120,height:120,left:80,top:30},smallSeat:{width:44,height:44},smallVehicle:{position:'absolute',left:0,top:0,width:44,height:44},vehicle:{position:'absolute',left:0,top:9,width:280,height:162},
 caption:{alignItems:'center',flexShrink:1},startupCaption:{position:'absolute',top:'50%',marginTop:112,left:16,right:16,alignItems:'center',gap:8},brand:{fontSize:28,fontWeight:'700',color:seatPalColors.forest},label:{fontSize:15,lineHeight:24,textAlign:'center',color:seatPalColors.forest},
});
