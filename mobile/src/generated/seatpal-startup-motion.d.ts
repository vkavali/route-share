export type StartupFrame = {
  seatX: number; seatY: number; seatScale: number; backAngle: number; backScaleX: number;
  railOpacity: number; carOpacity: number; carLineProgress: number; carFillOpacity: number;
  carDecorationOpacity: number; carSmallDetailsOpacity: number; driverOpacity: number; carX: number; carScaleX: number;
  bikeOpacity: number; bikeLineProgress: number; bikeFillOpacity: number; bikeDecorationOpacity: number;
  bikeRearDetailsOpacity: number; tankOpacity: number; engineOpacity: number; bikeX: number; bikeY: number; bikeScale: number;
  rearX: number; frontX: number; wheelY: number; wheelScale: number; wheelOpacity: number;
  rearRotation: number; frontRotation: number; wordOpacity: number; wordReveal: number; wordX: number;
  viewBoxX: number; viewBoxY: number; viewBoxWidth: number; viewBoxHeight: number;
};
export declare const STARTUP_MS: 3600;
export declare const STARTUP_ASSET_HASH: string;
export declare const VIEW_BOX: Readonly<{ x: 120; y: 130; width: 740; height: 310 }>;
export declare function frameAt(progress: number): StartupFrame;
export declare const STARTUP_FRAME0_SVG: string;
