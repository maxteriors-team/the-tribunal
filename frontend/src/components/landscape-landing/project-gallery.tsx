import Image from "next/image";

/**
 * Real photos of real Maxteriors installs. Nothing here is stock, generated, or
 * borrowed: a homeowner reading this page is judging whether we can light *their*
 * house, and a picture of someone else's work is a lie that survives right up
 * until the design visit.
 *
 * To add a photo:
 *   1. Drop the file in `frontend/public/landscape-lighting/`.
 *   2. Add an entry below with its real dimensions and an honest caption.
 *   3. Write `alt` for someone who cannot see it: describe the lighting, not
 *      the marketing. "Uplit maple over a brick ranch", not "beautiful lighting".
 *
 * An empty list renders nothing at all, which is correct: no gallery beats a
 * gallery of placeholders.
 */
export interface ProjectPhoto {
  src: string;
  alt: string;
  caption: string;
  width: number;
  height: number;
}

export const PROJECT_PHOTOS: ProjectPhoto[] = [
  {
    src: "/landscape-lighting/estate-driveway-path-lights.jpg",
    alt: "Brick estate at night with the facade washed in warm light and path lights tracing the curve of the driveway.",
    caption: "Driveway path lighting and facade wash",
    width: 1066,
    height: 1600,
  },
  {
    src: "/landscape-lighting/brick-colonial-uplighting.jpg",
    alt: "Brick home at night with maples uplit from below, warm light across the brick and low fixtures hidden in the beds.",
    caption: "Uplit maples and brick facade",
    width: 1600,
    height: 1066,
  },
  {
    src: "/landscape-lighting/walkway-covered-porch.jpg",
    alt: "Lit walkway running past clipped hedges to a covered porch with a warm glowing wood ceiling.",
    caption: "Walkway to a lit covered porch",
    width: 1600,
    height: 1066,
  },
  {
    src: "/landscape-lighting/porch-columns-beds.jpg",
    alt: "Covered porch at night, its wood ceiling and columns lit warm, with planting beds lit along the walk.",
    caption: "Porch ceiling, columns, and beds",
    width: 1066,
    height: 1600,
  },
  {
    src: "/landscape-lighting/stone-entry-pillars.jpg",
    alt: "Two stone entry pillars lit from the ground, framing a flagstone walk to a lit covered front porch.",
    caption: "Stone entry pillars and front walk",
    width: 1200,
    height: 800,
  },
  {
    src: "/landscape-lighting/patio-tree-uplighting.jpg",
    alt: "Patio table and chairs at night beside a large tree trunk lit from the base, with hostas lit in the bed.",
    caption: "Patio seating and tree uplighting",
    width: 1600,
    height: 1066,
  },
  {
    src: "/landscape-lighting/stone-pillar-walkway.jpg",
    alt: "Stone pillars along a walkway grazed with light from ground fixtures, showing the texture of the stone.",
    caption: "Grazed stone along a walkway",
    width: 1066,
    height: 1600,
  },
  {
    src: "/landscape-lighting/tree-row-uplighting.jpg",
    alt: "A row of young trees along a wood fence, each uplit from the base so the leaf canopy glows against the dark.",
    caption: "Uplit tree row along a fence line",
    width: 1200,
    height: 800,
  },
];

export function ProjectGallery({ photos = PROJECT_PHOTOS }: { photos?: ProjectPhoto[] }) {
  if (photos.length === 0) return null;

  return (
    <section className="border-t border-white/10 bg-[#0a0a0a]" aria-labelledby="gallery-heading">
      <div className="mx-auto w-full max-w-5xl px-5 py-16">
        <h2
          id="gallery-heading"
          className="max-w-2xl text-3xl font-semibold tracking-tight text-white sm:text-4xl"
        >
          Recent work, after dark
        </h2>
        <p className="mt-3 max-w-xl text-zinc-300">
          Every one of these is a real property we lit. Yours gets its own design.
        </p>

        <ul className="mt-10 grid grid-cols-1 gap-5 sm:grid-cols-2">
          {photos.map((photo) => (
            <li key={photo.src}>
              <figure className="overflow-hidden rounded-xl border border-white/10 bg-black/40">
                {/* Fixed 4:3 frame: the set mixes portrait and landscape
                    originals, and a uniform grid reads as finished work
                    rather than an unsorted camera roll. */}
                <Image
                  src={photo.src}
                  alt={photo.alt}
                  width={photo.width}
                  height={photo.height}
                  sizes="(min-width: 640px) 50vw, 100vw"
                  className="aspect-[4/3] w-full object-cover"
                />
                <figcaption className="px-4 py-3 text-sm text-zinc-400">{photo.caption}</figcaption>
              </figure>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}
