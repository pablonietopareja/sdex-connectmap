import type {
  ConfigPayload,
  ConfigStatus,
  ManualNetworkInterface,
  Settings,
} from "../types";
import { ConnectionForm } from "./ConnectionForm";
import { Modal } from "./Modal";
import { NetworkFallbackForm } from "./NetworkFallbackForm";

interface SettingsModalProps {
  open: boolean;
  status: ConfigStatus;
  settings: Settings;
  onClose: () => void;
  onSave: (payload: ConfigPayload) => Promise<void>;
  onSaveNetworkInterfaces: (
    interfaces: ManualNetworkInterface[],
  ) => Promise<void>;
}

export function SettingsModal({
  open,
  status,
  settings,
  onClose,
  onSave,
  onSaveNetworkInterfaces,
}: SettingsModalProps) {
  return (
    <Modal
      open={open}
      title="SDEX settings"
      eyebrow="Settings"
      size="large"
      onClose={onClose}
    >
      <ConnectionForm
        mode="settings"
        initial={status}
        onCancel={onClose}
        onSave={onSave}
      />
      <NetworkFallbackForm
        interfaces={settings.network_interfaces}
        onSave={onSaveNetworkInterfaces}
      />
    </Modal>
  );
}
