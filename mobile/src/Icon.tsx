import React from 'react';
import {SvgXml} from 'react-native-svg';
import {appIcon} from './generated/icons';

export function Icon({name, size = 22, color = '#173D32'}: {name: string; size?: number; color?: string}) {
  return <SvgXml xml={appIcon(name, {size, color})} width={size} height={size} />;
}
