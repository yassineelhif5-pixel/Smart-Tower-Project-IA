import type { MethodInfo } from "../../types/methodology";

export interface PageProps {
  info: MethodInfo;
  reload: () => void;
}
