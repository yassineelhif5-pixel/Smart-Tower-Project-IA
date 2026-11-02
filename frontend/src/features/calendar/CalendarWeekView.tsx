import { CalendarGrid, type GridProps } from "./CalendarGrid";

/** Vue Semaine : créneaux horaires, journées entières en tête. */
export function CalendarWeekView(props: GridProps) {
  return <CalendarGrid mode="timeGridWeek" {...props} />;
}
