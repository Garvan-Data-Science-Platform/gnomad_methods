"""Utils module containing generic functions that are useful for adding transcript expression-aware annotations."""
import logging
from typing import Callable, List, Optional, Tuple, Union

import hail as hl

from gnomad.utils.vep import add_most_severe_consequence_to_consequence

logging.basicConfig(
    format="%(asctime)s (%(name)s %(lineno)s): %(message)s",
    datefmt="%m/%d/%Y %I:%M:%S %p",
)
logger = logging.getLogger("transcript_annotation_utils")
logger.setLevel(logging.INFO)


def summarize_transcript_expression(
    mt: hl.MatrixTable,
    transcript_expression_expr: Union[hl.expr.NumericExpression, str] = "x",
    tissue_expr: Union[hl.expr.StringExpression, str] = "tissue",
    summary_agg_func: Optional[Callable] = None,
) -> Tuple[hl.Table, hl.Table]:
    """
    Summarize a transcript expression MatrixTable by transcript, gene, and tissue.

    The `summary_agg_func` argument allows the user to specify a Hail aggregation
    function to use to summarize the expression by tissue. By default, the median is
    used.

    The returned Table has a row annotation for each tissue containing the summarized
    tissue expression value.

    :param mt: MatrixTable of transcript (rows) expression quantifications (entry) by
        sample (columns).
    :param tissue_expr: Column expression indicating tissue type. Default is 'tissue'.
    :param transcript_expression_expr: Entry expression indicating transcript expression
        quantification. Default is 'x'.
    :param summary_agg_func: Optional aggregation function to use to summarize the
        transcript expression quantification by tissue. Example: `hl.agg.mean`. Default
        is None, which will use a median aggregation.
    :return: A Table of summarized transcript expression by tissue and a Table of
        summarized gene expression by tissue.
    """
    if summary_agg_func is None:
        summary_agg_func = lambda x: hl.median(hl.agg.collect(x))

    mt = mt.group_cols_by(tissue=tissue_expr).aggregate(
        tx=summary_agg_func(transcript_expression_expr)
    )

    transcript_ht = mt.rename({"tx": ""}).make_table()
    transcript_ht = transcript_ht.key_by("transcript_id", "gene_id")

    gene_ht = transcript_ht.group_by("gene_id").aggregate(
        **{
            tissue: hl.agg.sum(transcript_ht[tissue])
            for tissue in list(transcript_ht.row_value)
        }
    )

    return transcript_ht, gene_ht


def tissue_expression_ht_to_array(
    ht: hl.Table,
    tissues: Optional[List[str]] = None,
    tissues_to_filter: Optional[List[str]] = None,
) -> hl.Table:
    """
    Convert a Table with a row annotation for each tissue to a Table with tissues as an array.

    The output is a Table with a field 'tissue_expression' containing an array of
    summarized expression values by tissue, where the order of tissues in the array is
    indicated by the "tissues" global annotation.

    :param ht: Table with a row annotation for each tissue.
    :param tissues: Optional list of tissues to keep in the 'tissue_expression' array.
        Default is all non-key rows in the Table.
    :param tissues_to_filter: Optional list of tissues to exclude from the tissue
        expression array.
    :return: Table with a field 'tissue_expression' containing an array of summarized
        expression values by tissue.
    """
    if tissues is None:
        tissues = list(ht.row_value)

    if tissues_to_filter is not None:
        logger.info("Filtering tissues: %s", tissues_to_filter)
        tissues = [t for t in tissues if t not in tissues_to_filter]

    ht = ht.select_globals(tissues=tissues)
    ht = ht.select(tissue_expression=[ht[t] for t in tissues])

    return ht


def get_expression_proportion(
    transcript_ht: hl.Table,
    gene_ht: hl.Table,
    tissues_to_filter: Optional[List[str]] = None,
) -> hl.Table:
    """
    Calculate the proportion of expression of transcript to gene per tissue.

    :param transcript_ht: Table of summarized transcript expression by tissue.
    :param gene_ht: Table of summarized gene expression by tissue.
    :param tissues_to_filter: Optional list of tissues to filter out
    :return: Table with expression proportion of transcript to gene per tissue
        and mean expression proportion across tissues.
    """
    transcript_ht = tissue_expression_ht_to_array(
        transcript_ht, tissues_to_filter=tissues_to_filter
    )
    gene_ht = tissue_expression_ht_to_array(
        gene_ht, tissues=hl.eval(transcript_ht.tissues)
    )

    # Join the transcript expression table and gene expression table.
    transcript_ht = transcript_ht.annotate(
        gene_expression=gene_ht[transcript_ht.gene_id].tissue_expression
    )

    # Calculate the proportion of expression of transcript to gene per tissue.
    transcript_ht = transcript_ht.annotate(
        exp_prop=hl.or_else(
            transcript_ht.transcript_expression / transcript_ht.gene_expression,
            hl.empty_array(hl.tfloat64),
        ),
    )
    # Calculate the mean expression proportion across tissues.
    transcript_ht = transcript_ht.annotate(
        exp_prop_mean=hl.mean(
            hl.filter(lambda e: ~hl.is_nan(e), transcript_ht.exp_prop),
        )
    )

    return transcript_ht


def tx_annotate_variants(
    variant_ht: hl.Table,
    tx_ht: hl.Table,
    filter_to_protein_coding: bool = True,
    filter_to_genes: List[str] = None,
    filter_to_csqs: List[str] = None,
    filter_to_homs: bool = False,
) -> hl.Table:
    """
    Annotate variants with transcript-based expression values or expression proportion from GTEx.

    :param variant_ht: Table of variants to annotate, it should contain at
        least the following nested fields: `vep.transcript_consequences`,
        `freq`.
    :param tx_ht: Table of transcript expression information.
    :param filter_to_protein_coding: If True, filter to protein coding
        transcripts. Default is True.
    :param filter_to_genes: List of genes to filter to.
    :param filter_to_csqs: List of consequence terms to filter to.
    :param filter_to_homs: If True, filter to variants with at least one
        homozygote in `freq` field. Default is False.
    :return: MatrixTable with transcript expression information annotated
    """
    # GTEx data has transcript IDs without version numbers, so we need to
    # remove the version numbers from the transcript IDs in the variant table
    tx_ht = tx_ht.key_by()
    tx_ht = tx_ht.annotate(transcript_id=tx_ht.transcript_id.split("\\.")[0])
    tx_ht = tx_ht.key_by(tx_ht.transcript_id)

    variant_ht = variant_ht.annotate(
        vep=variant_ht.vep.annotate(
            transcript_consequences=variant_ht.vep.transcript_consequences.map(
                add_most_severe_consequence_to_consequence
            )
        )
    )

    # Explode the transcript consequences to be able to key by transcript ID
    variant_ht = variant_ht.explode(variant_ht.vep.transcript_consequences)

    if filter_to_protein_coding:
        variant_ht = variant_ht.filter(
            variant_ht.vep.transcript_consequences.biotype == "protein_coding"
        )

    if filter_to_genes:
        variant_ht = variant_ht.filter(
            hl.literal(filter_to_genes).contains(
                variant_ht.vep.transcript_consequences.gene_id
            )
        )

    if filter_to_csqs:
        variant_ht = variant_ht.filter(
            hl.literal(filter_to_csqs).contains(
                variant_ht.vep.transcript_consequences.most_severe_consequence
            )
        )

    if filter_to_homs:
        variant_ht = variant_ht.filter(variant_ht.freq[0].homozygote_count > 0)

    # Annotate the variant table with the transcript expression information
    variant_ht = variant_ht.annotate(
        tx_data=tx_ht[variant_ht.vep.transcript_consequences.transcript_id]
    )

    # Aggregate the transcript expression information by gene, csq, etc.
    # TODO: Should we filter to only exonic variants since it's mostly exomes
    #  data?
    tx_annot_ht = variant_ht.group_by(
        gene_id=variant_ht.vep.transcript_consequences.gene_id,
        locus=variant_ht.locus,
        alleles=variant_ht.alleles,
        gene_symbol=variant_ht.vep.transcript_consequences.gene_symbol,
        csq=variant_ht.vep.transcript_consequences.most_severe_consequence,
        lof=variant_ht.vep.transcript_consequences.lof,
        lof_flags=variant_ht.vep.transcript_consequences.lof_flags,
    ).aggregate(
        tx_annotation=hl.agg.array_sum(variant_ht.tx_data.transcript_expression),
        mean_proportion=hl.agg.sum(variant_ht.tx_data.exp_prop_mean),
    )

    # Remove unnecessary global annotations and add tissue and
    # expression_type in global annotations
    tx_annot_ht = tx_annot_ht.select_globals().annotate_globals(
        tissues=tx_ht.index_globals().tissues,
    )

    tx_annot_ht = tx_annot_ht.key_by(tx_annot_ht.locus, tx_annot_ht.alleles)

    return tx_annot_ht
