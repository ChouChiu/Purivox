import { useCallback, useState } from "react";

import type { OutputTracks } from "../../shared/jobs";
import type { PreparedFile } from "../../shared/runtime/types";
import { defaultOutputName, normalizedOutputName } from "./job";

/**
 * The output file name and whose choice it is, by the desktop's rules.
 *
 * A name the page derived from the recording follows the recording and the
 * export choice; one the user typed stays theirs until they clear the field.
 */
export function useOutputName() {
	const [name, setName] = useState("");
	const [typed, setTyped] = useState(false);

	/** Name the output after the recording and the export choice. */
	const rename = useCallback((stage: PreparedFile, tracks: OutputTracks) => {
		setName(defaultOutputName(stage, tracks));
		setTyped(false);
	}, []);

	const type = useCallback((value: string) => {
		setName(value);
		setTyped(true);
	}, []);

	/** Leaving the field: refill an emptied one, and make any other a `.wav`. */
	const settle = useCallback(
		(stage: PreparedFile | null, tracks: OutputTracks) => {
			if (name.trim() !== "") {
				setName(normalizedOutputName(name));
			} else if (stage !== null) {
				setName(defaultOutputName(stage, tracks));
				setTyped(false);
			}
		},
		[name],
	);

	return { name, typed, rename, type, settle };
}
