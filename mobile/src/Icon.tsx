import React from 'react';
import {SvgXml} from 'react-native-svg';
import {appIcon} from './generated/icons';
import {SeatPalTheme} from './SeatPalTheme';

export function Icon({name, size = 22, color = SeatPalTheme.colors.text}: {name: string; size?: number; color?: string}) {
  return <SvgXml xml={appIcon(name, {size, color})} width={size} height={size} />;
}
