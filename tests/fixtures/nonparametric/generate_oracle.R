options(digits = 17)

# Optional external fixture generator.  This file is never executed by the
# production pack; it only emits base-R reference values for test maintenance.
x <- c(1, 2, 3, 4)
y <- c(3, 4, 5, 8)
paired_left <- c(2, 4, 7, 9)
paired_right <- c(1, 3, 5, 8)
groups <- list(x, y, c(6, 7, 9, 10))

mw <- wilcox.test(x, y, exact = TRUE)
ws <- wilcox.test(paired_left, paired_right, paired = TRUE, exact = TRUE)
kw <- kruskal.test(groups)
sp <- cor.test(x, y, method = "spearman", exact = TRUE)
kt <- cor.test(x, y, method = "kendall", exact = TRUE)

cat(sprintf("mann_whitney,%.17g,%.17g\n", mw$statistic, mw$p.value))
cat(sprintf("wilcoxon,%.17g,%.17g\n", ws$statistic, ws$p.value))
cat(sprintf("kruskal,%.17g,%.17g\n", kw$statistic, kw$p.value))
cat(sprintf("spearman,%.17g,%.17g\n", sp$estimate, sp$p.value))
cat(sprintf("kendall,%.17g,%.17g\n", kt$estimate, kt$p.value))
