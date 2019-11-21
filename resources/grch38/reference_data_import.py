import argparse
from .reference_data import *

NO_CHR_TO_CHR_CONTIG_RECODING = {str(x): f'chr{x}' for x in list(range(1, 23)) + ['X', 'Y']}
NO_CHR_TO_CHR_CONTIG_RECODING['MT'] = 'chrM'


def import_purcell_5k() -> hl.Table:
    p5k = hl.import_locus_intervals(purcell_5k.source_path, reference_genome='GRCh37')
    p5k = p5k.annotate(
        start=hl.liftover(p5k.interval.start, 'GRCh38'),
        end=hl.liftover(p5k.interval.start, 'GRCh38')
    )
    p5k = p5k.filter(
        (p5k.start.contig == 'chr' + p5k.interval.start.contig) &
        (p5k.end.contig == 'chr' + p5k.interval.end.contig)
    )
    p5k = p5k.key_by()
    p5k = p5k.select(
        locus=p5k.start,
        locus_b37=p5k.interval.start
    )
    return p5k.key_by('locus')


def main(args):

    hl.init(log='/load_resources.hail.log', default_reference='GRCh38')
    hl.get_reference('GRCh37').add_liftover('gs://hail-common/references/grch37_to_grch38.over.chain.gz', hl.get_reference('GRCh38'))

    if args.purcell_5k:
        import_purcell_5k().write(purcell_5k.path, overwrite=args.overwrite)

    if args.clinvar:
        hl.import_vcf(
            clinvar.source_path,
            force_bgz=True,
            contig_recoding=NO_CHR_TO_CHR_CONTIG_RECODING,
            skip_invalid_loci=True,
            min_partitions=100
        ).rows().write(clinvar.path, overwrite=args.overwrite)

    if args.na12878:
        hl.import_vcf(
            na12878_giab.source_path, force_bgz=True, min_partitions=100
        ).write(na12878_giab.path, overwrite=args.overwrite)

    if args.dbsnp:
        hl.import_vcf(
            dbsnp.source_path,
            force_bgz=True,
            contig_recoding=NO_CHR_TO_CHR_CONTIG_RECODING,
            skip_invalid_loci=True,
            header_file=dbsnp.attributes['vcf_header_path'],
            min_partitions=400
        ).rows().write(dbsnp.path, overwrite=args.overwrite)

    if  args.hapmap:
        hl.import_vcf(hapmap.source_path, force_bgz=True).rows().write(hapmap.path, overwrite=args.overwrite)

    if args.kgp_omni:
        hl.import_vcf(kgp_omni.source_path, force_bgz=True).rows().write(kgp_omni.path, overwrite=args.overwrite)

    if args.kgp:
        hl.import_vcf(kgp.source_path, force_bgz=True).rows().write(kgp.path, overwrite=args.overwrite)

    if args.mills:
        hl.import_vcf(mills.source_path, force_bgz=True).rows().write(mills.path, overwrite=args.overwrite)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--purcell_5k', help='Lift-over Purcell5k sites (from intervals)', action='store_true')
    parser.add_argument('--clinvar', help='Import clinvar VCF', action='store_true')
    parser.add_argument('--na12878', help='Imports GiaB NA12878', action='store_true')
    parser.add_argument('--dbsnp', help='Imports DBSNP', action='store_true')
    parser.add_argument('--hapmap', help='Imports HapMap', action='store_true')
    parser.add_argument('--kgp_omni', help='Imports Omni / KGP sites VCF', action='store_true')
    parser.add_argument('--kgp', help='Imports 1000 Genomes sites VCF', action='store_true')
    parser.add_argument('--mills', help='Imports Mills Devine indel sites VCF', action='store_true')
    parser.add_argument('--overwrite', help='Overwrites existing files', action='store_true')
    main(parser.parse_args())