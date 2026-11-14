import { CalendarGrid, type GridProps } from "./CalendarGrid";

/** Vue Mois : glisser-déposer pour déplacer, poignée pour allonger. */
export function CalendarMonthView(props: GridProps) {
  return <CalendarGrid mode="dayGridMonth" {...props} />;
}
