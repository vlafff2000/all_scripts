// Настройки вида таблиц; ключи те же, что в Атласе. После обновления копии графиков (chartPrefs.ts) эти значения
// там тоже объявлены: источник один — localStorage, поэтому настройка общая.
import { pref } from '../chart/chartPrefs'

export const tableBars = pref<boolean>('atlas.table.bars', true)
export const tableSync = pref<boolean>('atlas.table.sync', true, raw => raw !== 'false')
