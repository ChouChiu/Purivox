import {
	Button,
	Field,
	makeStyles,
	Text,
	tokens,
} from "@fluentui/react-components";
import { useCallback, useEffect, useRef } from "react";

import { useLanguage } from "../i18n/context";

/** Every container libsndfile reads, plus what the browser decoder covers. */
export const AUDIO_ACCEPT = ".wav,.flac,.mp3,.m4a,.ogg,.opus,audio/*";

const useStyles = makeStyles({
	row: {
		display: "flex",
		gap: tokens.spacingHorizontalS,
		// Below the desktop's PORTRAIT breakpoint the control stacks above the
		// path rather than sharing a line that fits neither.
		flexDirection: "column",
		alignItems: "stretch",
		"@media (min-width: 620px)": { flexDirection: "row", alignItems: "center" },
	},
	chosen: {
		display: "flex",
		flexDirection: "column",
		flex: "1 1 auto",
		minWidth: 0,
	},
	name: {
		minWidth: 0,
		overflow: "hidden",
		textOverflow: "ellipsis",
		whiteSpace: "nowrap",
		color: tokens.colorNeutralForeground2,
	},
});

interface Props {
	label: string;
	hint?: string;
	value: string | null;
	multiple?: boolean;
	disabled?: boolean;
	onPick(files: File[]): void;
	/** Hand the caller a way to open this picker, for the Ctrl+O shortcut. */
	registerOpen?(open: () => void): void;
	/** Shown under the chosen path, for what the decoder read out of it. */
	detail?: React.ReactNode;
}

export function FilePicker({
	label,
	hint,
	value,
	multiple,
	disabled,
	onPick,
	registerOpen,
	detail,
}: Props) {
	const styles = useStyles();
	const { t } = useLanguage();
	const input = useRef<HTMLInputElement>(null);
	const open = useCallback(() => input.current?.click(), []);

	useEffect(() => registerOpen?.(open), [open, registerOpen]);

	return (
		<Field label={label} hint={hint}>
			<div className={styles.row}>
				<Button appearance="secondary" disabled={disabled} onClick={open}>
					{t("browse")}
				</Button>
				<div className={styles.chosen}>
					<Text className={styles.name} title={value ?? undefined}>
						{value ?? t("file_select")}
					</Text>
					{detail}
				</div>
				<input
					ref={input}
					type="file"
					hidden
					accept={AUDIO_ACCEPT}
					multiple={multiple}
					onChange={(event) => {
						const files = Array.from(event.target.files ?? []);
						// Clear the element so picking the same file twice still fires.
						event.target.value = "";
						if (files.length > 0) onPick(files);
					}}
				/>
			</div>
		</Field>
	);
}
