#!/bin/bash
# Stock QIIME 2 2026.1 workflow whose exports are audited with the qiime2-export
# profile (Table 6 of the paper). One run per cohort; nothing in the workflow is
# specific to the audit. Reference: SILVA 138.1 SSURef NR99 (the same FASTA and
# taxonomy the wrapper pipeline uses), imported once.
#
#   bash commands.sh ablacja_PRJNA420417 ablacja_PRJNA732664 ablacja_PRJNA763023 mock
#
# expects data/<cohort>/<sample>/<sample>_{1,2}.fastq.gz (see ../accessions.tsv).
set -u
P=${PIPELINE_DATA:-$PWD/data}        # where the FASTQ files live
S=${STOCK_OUT:-$PWD/stock}           # where the runs are written
mkdir -p $S/refs
if [ ! -f $S/refs/silva-tax.qza ]; then
  sed '/^>/!y/Uu/Tt/' silva_seqs.fasta > $S/refs/silva_seqs_dna.fasta   # SILVA ships RNA
  qiime tools import --type 'FeatureData[Sequence]' --input-path $S/refs/silva_seqs_dna.fasta --output-path $S/refs/silva-seqs.qza
  qiime tools import --type 'FeatureData[Taxonomy]' --input-format HeaderlessTSVTaxonomyFormat --input-path silva_taxonomy.tsv --output-path $S/refs/silva-tax.qza
  qiime feature-classifier makeblastdb --i-sequences $S/refs/silva-seqs.qza --o-database $S/refs/silva-db.qza
fi
for C in "$@"; do
  O=$S/$C; mkdir -p $O/export
  printf "sample-id\tforward-absolute-filepath\treverse-absolute-filepath\n" > $O/manifest.tsv
  for d in $P/$C/*/; do n=$(basename $d); printf "%s\t%s\t%s\n" "$n" "$(ls $d/*_1.fastq.gz)" "$(ls $d/*_2.fastq.gz)" >> $O/manifest.tsv; done
  qiime tools import --type 'SampleData[PairedEndSequencesWithQuality]' --input-format PairedEndFastqManifestPhred33V2 \
      --input-path $O/manifest.tsv --output-path $O/demux.qza
  qiime cutadapt trim-paired --i-demultiplexed-sequences $O/demux.qza \
      --p-front-f CCTACGGGNGGCWGCAG --p-front-r GACTACHVGGGTATCTAATCC --p-cores 16 --o-trimmed-sequences $O/trimmed.qza
  qiime dada2 denoise-paired --i-demultiplexed-seqs $O/trimmed.qza --p-trunc-len-f 230 --p-trunc-len-r 220 --p-n-threads 24 \
      --o-table $O/table.qza --o-representative-sequences $O/rep-seqs.qza --o-denoising-stats $O/stats.qza \
      --o-base-transition-stats $O/transition-stats.qza
  qiime feature-classifier classify-consensus-blast --i-query $O/rep-seqs.qza \
      --i-blastdb $S/refs/silva-db.qza --i-reference-taxonomy $S/refs/silva-tax.qza --p-num-threads 24 \
      --o-classification $O/taxonomy.qza --o-search-results $O/blast-hits.qza
  qiime tools export --input-path $O/stats.qza --output-path $O/export      # -> stats.tsv
  qiime tools export --input-path $O/taxonomy.qza --output-path $O/export   # -> taxonomy.tsv
  cp $O/stats.qza $O/table.qza $O/rep-seqs.qza $O/taxonomy.qza $O/export/
  # the parameters the analyst configured, for the provenance check:
  cat > $O/export/dada2_config.json <<'EOF'
{"trunc_len_f": 230, "trunc_len_r": 220, "max_ee_f": 2.0, "max_ee_r": 2.0, "trunc_q": 2,
 "pooling_method": "independent", "chimera_method": "consensus"}
EOF
done
# audit:
#   ampliconaudit stock/ --profile qiime2-export        (run directories = the export/ folders)
