import React,{useCallback,useEffect,useMemo,useRef,useState} from 'react';
import {AccessibilityInfo,ActivityIndicator,Animated,AppState,Easing,StyleSheet,Text,View,type LayoutChangeEvent,type StyleProp,type ViewStyle} from 'react-native';
import Svg,{ClipPath,G,Path,Rect,parse} from 'react-native-svg';
import {seatPalColors} from './SeatPalArt';
import {STARTUP_MS,frameAt} from './generated/seatpal-startup-motion';
import startupParts from '../assets/seatpal/startup-motion.json';

const AnimatedGroup=Animated.createAnimatedComponent(G<{display?:'none'}>);
const AnimatedPath=Animated.createAnimatedComponent(Path);
const AnimatedRect=Animated.createAnimatedComponent(Rect);
const samples=Array.from({length:181},(_,index)=>index/180);
const sampledFrames=samples.map(frameAt);
type FrameKey=keyof ReturnType<typeof frameAt>;
const frameValue=(progress:Animated.Value,key:FrameKey)=>progress.interpolate({inputRange:samples,outputRange:sampledFrames.map(frame=>frame[key]),extrapolate:'clamp'});
const parts=startupParts.parts;
const wordmarkClip=startupParts.wordmarkClip;
// Font aliases registered by expo-font are single family names on native; SVG
// does not reliably resolve CSS-style family lists on Android or iOS.
const wordmarkXml=parts.wordmark.xml.replace('font-family="Manrope, Segoe UI, sans-serif"','font-family="Manrope700"');
type PartName=Exclude<keyof typeof parts,'carTracePaths'|'bikeTracePaths'>;
// Keep every layer in the shared scene coordinates. A nested native Svg is a
// separate viewport; its x/y do not position it like a browser's nested <svg>.
const nativeParts=Object.fromEntries(Object.entries(parts).filter(([,part])=>!Array.isArray(part)).map(([name,part])=>[name,parse(name==='wordmark'?wordmarkXml:(part as {xml:string}).xml)?.children])) as Record<PartName,React.ReactNode>;

// One startup clock is shared across font/auth remounts. Background time is paused,
// and once the scene reaches its final logo it never replays in the same process.
let startupElapsedMs=0;
let startupRunningSince:number|null=null;
let startupWasStarted=false;
const elapsedStartupMs=(now:number)=>startupElapsedMs+(startupRunningSince===null?0:Math.max(0,now-startupRunningSince));
const startupFraction=()=>Math.min(1,Math.max(0,elapsedStartupMs(Date.now())/STARTUP_MS));
const startStartupClock=(now:number)=>{if(!startupWasStarted){startupWasStarted=true;startupElapsedMs=0;startupRunningSince=now;}};
const pauseStartupClock=(now:number)=>{if(startupRunningSince!==null){startupElapsedMs=Math.min(STARTUP_MS,startupElapsedMs+Math.max(0,now-startupRunningSince));startupRunningSince=null;}};
const resumeStartupClock=(now:number)=>{if(startupWasStarted&&startupRunningSince===null&&startupElapsedMs<STARTUP_MS)startupRunningSince=now;};
const finishStartupClock=()=>{startupWasStarted=true;startupElapsedMs=STARTUP_MS;startupRunningSince=null;};

type Trace=typeof parts.carTracePaths[number];
type Props={label:string;variant?:'compact'|'startup';fontFamily?:string;style?:StyleProp<ViewStyle>};
export function SeatPalLoader({label,variant='compact',fontFamily,style}:Props){
 const isStartup=variant==='startup';
 if(isStartup){startStartupClock(Date.now());if(AppState.currentState!=='active')pauseStartupClock(Date.now());}
 const [reduceMotion,setReduceMotion]=useState<boolean|null>(null),[motionPreferenceReady,setMotionPreferenceReady]=useState(false),[foreground,setForeground]=useState(AppState.currentState==='active'),[traceLengths,setTraceLengths]=useState<{car:Array<number|null>;bike:Array<number|null>}|null>(null);
 const progress=useRef(new Animated.Value(isStartup?startupFraction():1)).current;
 const animatedFrames=useMemo(()=>Object.fromEntries((Object.keys(sampledFrames[0]) as FrameKey[]).map(key=>[key,frameValue(progress,key)])) as Record<FrameKey,ReturnType<typeof frameValue>>,[progress]);
 const [cameraProgress,setCameraProgress]=useState(isStartup?startupFraction():1);
 useEffect(()=>{
  if(!isStartup)return;
  // Svg translates viewBox to native minX/minY/vbWidth/vbHeight during render.
  // Animated.setNativeProps({viewBox}) bypasses that conversion on iOS.
  const listener=progress.addListener(({value})=>setCameraProgress(value));
  return()=>progress.removeListener(listener);
 },[isStartup,progress]);
 const running=useRef<Animated.CompositeAnimation|null>(null),traceMeasureRequested=useRef(false),traceMeasureFrame=useRef<number|null>(null),traceRefs=useRef<{car:Array<Path|null>;bike:Array<Path|null>}>({car:[],bike:[]});
 useEffect(()=>{
  let alive=true,preferenceChanged=false;
  const preference=AccessibilityInfo.addEventListener('reduceMotionChanged',value=>{preferenceChanged=true;setMotionPreferenceReady(true);setReduceMotion(value);});
  void AccessibilityInfo.isReduceMotionEnabled().then(value=>{if(alive&&!preferenceChanged){setMotionPreferenceReady(true);setReduceMotion(value);}}).catch(()=>{if(alive){setReduceMotion(true);setMotionPreferenceReady(true);}});
  const appState=AppState.addEventListener('change',state=>{
   const now=Date.now();
   if(isStartup){if(state==='active')resumeStartupClock(now);else pauseStartupClock(now);}
   if(state!=='active')running.current?.stop();
   setForeground(state==='active');
  });
  return()=>{alive=false;preference.remove();appState.remove();running.current?.stop();if(traceMeasureFrame.current!==null){cancelAnimationFrame(traceMeasureFrame.current);traceMeasureFrame.current=null;}};
 },[isStartup]);
 useEffect(()=>{
  running.current?.stop();
  if(!isStartup)return;
  if(motionPreferenceReady&&reduceMotion){finishStartupClock();progress.setValue(1);return;}
  const fraction=startupFraction();
  progress.setValue(fraction);
  if(!motionPreferenceReady||!foreground||fraction>=1)return;
  const animation=Animated.timing(progress,{toValue:1,duration:Math.max(0,STARTUP_MS*(1-fraction)),easing:Easing.linear,useNativeDriver:false,isInteraction:false});
  running.current=animation;
  animation.start(({finished})=>{if(finished)pauseStartupClock(Date.now());});
  return()=>{running.current?.stop();running.current=null;};
 },[foreground,isStartup,motionPreferenceReady,progress,reduceMotion]);

 const measureTraces=useCallback((_event:LayoutChangeEvent)=>{
  if(traceMeasureRequested.current||!isStartup)return;
  traceMeasureRequested.current=true;
  traceMeasureFrame.current=requestAnimationFrame(()=>{
   traceMeasureFrame.current=null;
   const measure=(items:Trace[],refs:Array<Path|null>)=>items.map((_,index)=>{
    try{const length=refs[index]?.getTotalLength();return typeof length==='number'&&Number.isFinite(length)&&length>0?length:null;}catch{return null;}
   });
   setTraceLengths({car:measure(parts.carTracePaths,traceRefs.current.car),bike:measure(parts.bikeTracePaths,traceRefs.current.bike)});
  });
 },[isStartup]);
 const part=(name:PartName)=>nativeParts[name];
 const frame=(key:FrameKey)=>reduceMotion===true?frameAt(1)[key]:animatedFrames[key];
 const layout=variant==='startup'?styles.startup:styles.compact;
 if(!isStartup)return <View testID="seatpal-loader-compact" accessible accessibilityRole="progressbar" accessibilityLabel={label} accessibilityState={{busy:true}} accessibilityLiveRegion="polite" style={[layout,style]}>
  <ActivityIndicator size="small" color={seatPalColors.forest}/>
  <Text style={[styles.label,fontFamily?{fontFamily}:null]}>{label}</Text>
 </View>;

 const drawTraces=(kind:'car'|'bike',items:Trace[],progressKey:'carLineProgress'|'bikeLineProgress')=>items.map((trace,index)=>{
  const length=traceLengths?.[kind][index]??null,ref=(node:Path|null)=>{traceRefs.current[kind][index]=node;};
  const dashProps=length===null?(traceLengths===null&&reduceMotion!==true?{strokeDasharray:[1000000,1000000],strokeDashoffset:1000000}:{}):{strokeDasharray:[length,length],strokeDashoffset:Animated.multiply(Animated.subtract(1,frame(progressKey)),length)};
  return <AnimatedPath key={`${kind}-${index}`} ref={ref} d={trace.d} fill={trace.fill} stroke={trace.stroke} strokeWidth={trace.strokeWidth} strokeLinecap={trace.strokeLinecap as 'round'|'butt'|'square'} strokeLinejoin={trace.strokeLinejoin as 'round'|'miter'|'bevel'} {...dashProps}/>;
 });
 const seatX=frame('seatX'),seatY=frame('seatY'),seatScale=frame('seatScale');
 const camera=frameAt(reduceMotion===true?1:cameraProgress);
 // Explicitly exclude zero-opacity groups: nested native SVG groups can reset
 // CGContext alpha when initially mounted at zero under Fabric.
 const visibility=(key:FrameKey):'none'|undefined=>camera[key]===0?'none':undefined;
 const wheelGroup=(name:'rearWheel'|'frontWheel',xKey:'rearX'|'frontX',rotationKey:'rearRotation')=>
  <AnimatedGroup translateX={frame(xKey)} translateY={frame('wheelY')} scale={frame('wheelScale')}>
   <AnimatedGroup rotation={frame(rotationKey)} originX={0} originY={0}>{part(name)}</AnimatedGroup>
  </AnimatedGroup>;
 return <View testID="seatpal-loader-startup" accessible accessibilityRole="progressbar" accessibilityLabel={label} accessibilityState={{busy:true}} accessibilityLiveRegion="polite" style={[layout,style]}>
  <View testID="seatpal-loader-stage" onLayout={measureTraces} importantForAccessibility="no-hide-descendants" accessibilityElementsHidden style={styles.stageFrame}>
   <Svg width="100%" height="100%" viewBox={`${camera.viewBoxX} ${camera.viewBoxY} ${camera.viewBoxWidth} ${camera.viewBoxHeight}`} preserveAspectRatio="xMidYMid meet">
    <AnimatedGroup display={visibility('carOpacity')} opacity={frame('carOpacity')} translateX={frame('carX')} scaleX={frame('carScaleX')} originX={0}>
     <AnimatedGroup display={visibility('carFillOpacity')} opacity={frame('carFillOpacity')}>{part('carBody')}</AnimatedGroup>
     {drawTraces('car',parts.carTracePaths,'carLineProgress')}
     <AnimatedGroup display={visibility('carDecorationOpacity')} opacity={frame('carDecorationOpacity')}>{part('carDecoration')}</AnimatedGroup>
     <AnimatedGroup display={visibility('carSmallDetailsOpacity')} opacity={frame('carSmallDetailsOpacity')}>{part('carSmallDetails')}</AnimatedGroup>
     <AnimatedGroup display={visibility('driverOpacity')} opacity={frame('driverOpacity')}>{part('driverSeat')}</AnimatedGroup>
    </AnimatedGroup>
    <AnimatedGroup display={visibility('bikeOpacity')} opacity={frame('bikeOpacity')} translateX={frame('bikeX')} translateY={frame('bikeY')} scale={frame('bikeScale')}>
     <AnimatedGroup display={visibility('bikeFillOpacity')} opacity={frame('bikeFillOpacity')}>{part('bikeBody')}</AnimatedGroup>
     {drawTraces('bike',parts.bikeTracePaths,'bikeLineProgress')}
     <AnimatedGroup display={visibility('bikeDecorationOpacity')} opacity={frame('bikeDecorationOpacity')}>{part('bikeDecoration')}</AnimatedGroup>
     <AnimatedGroup display={visibility('tankOpacity')} opacity={frame('tankOpacity')}>{part('tankFill')}</AnimatedGroup>
     <AnimatedGroup display={visibility('engineOpacity')} opacity={frame('engineOpacity')}>{part('bikeEngine')}</AnimatedGroup>
     <AnimatedGroup display={visibility('bikeRearDetailsOpacity')} opacity={frame('bikeRearDetailsOpacity')}>{part('bikeRearDetails')}</AnimatedGroup>
    </AnimatedGroup>
    <AnimatedGroup display={visibility('wheelOpacity')} opacity={frame('wheelOpacity')}>
     {wheelGroup('rearWheel','rearX','rearRotation')}
     <AnimatedGroup translateX={frame('frontX')} translateY={frame('wheelY')} scale={frame('wheelScale')}>
      <AnimatedGroup rotation={frame('frontRotation')} originX={0} originY={0}>{part('frontWheel')}</AnimatedGroup>
     </AnimatedGroup>
    </AnimatedGroup>
    <AnimatedGroup translateX={seatX} translateY={seatY} scale={seatScale}>
     <AnimatedGroup rotation={frame('backAngle')} scaleX={frame('backScaleX')} originX={0} originY={0}>{part('seatBack')}</AnimatedGroup>
     <AnimatedGroup display={visibility('railOpacity')} opacity={frame('railOpacity')}>{part('seatRail')}</AnimatedGroup>
     {part('seatBase')}
    </AnimatedGroup>
    <ClipPath id="seatpal-word-reveal"><AnimatedRect x={wordmarkClip.x} y={wordmarkClip.y} width={Animated.multiply(wordmarkClip.width,frame('wordReveal'))} height={wordmarkClip.height}/></ClipPath>
    <AnimatedGroup display={visibility('wordOpacity')} opacity={frame('wordOpacity')} translateX={frame('wordX')} clipPath="url(#seatpal-word-reveal)">
     {part('wordmark')}
    </AnimatedGroup>
   </Svg>
  </View>
 </View>;
}
const styles=StyleSheet.create({
 startup:{flex:1,width:'100%',alignItems:'center',justifyContent:'center',paddingHorizontal:24,backgroundColor:seatPalColors.ivory,minHeight:280},
 compact:{alignItems:'center',justifyContent:'center',gap:12,padding:18,borderRadius:20,backgroundColor:seatPalColors.ivory,maxWidth:300},
 stageFrame:{width:'100%',maxWidth:360,aspectRatio:740/310,alignSelf:'center'},
 label:{fontSize:15,lineHeight:24,textAlign:'center',color:seatPalColors.forest},
});
