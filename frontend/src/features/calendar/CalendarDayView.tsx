import { CalendarGrid, type GridProps } from "./CalendarGrid";

/** Vue Jour : détail horaire d'une journée. */
export function CalendarDayView(props: GridProps) {
  return <CalendarGrid mode="timeGridDay" {...props} />;
}
