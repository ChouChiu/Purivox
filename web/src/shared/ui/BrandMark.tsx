/**
 * The application mark, from the file the desktop draws its window icon from.
 *
 * `scripts/build-assets.mjs` copies `src/resources/purivox.svg` into the site's
 * public files, so the page and the desktop cannot drift apart.
 */
export function BrandMark({ size = 32 }: { size?: number }) {
	return (
		<img
			src={`${import.meta.env.BASE_URL}purivox.svg`}
			width={size}
			height={size}
			alt="Purivox"
			style={{ borderRadius: size / 4.6, display: "block", flexShrink: 0 }}
		/>
	);
}
