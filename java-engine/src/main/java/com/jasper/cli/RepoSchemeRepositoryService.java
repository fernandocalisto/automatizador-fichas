package com.jasper.cli;

import net.sf.jasperreports.engine.JRException;
import net.sf.jasperreports.engine.JRRuntimeException;
import net.sf.jasperreports.engine.JasperCompileManager;
import net.sf.jasperreports.engine.JasperReport;
import net.sf.jasperreports.engine.JasperReportsContext;
import net.sf.jasperreports.engine.design.JasperDesign;
import net.sf.jasperreports.engine.util.JRLoader;
import net.sf.jasperreports.engine.xml.JRXmlLoader;
import net.sf.jasperreports.repo.FileRepositoryService;
import net.sf.jasperreports.repo.InputStreamResource;
import net.sf.jasperreports.repo.PersistenceService;
import net.sf.jasperreports.repo.PersistenceUtil;
import net.sf.jasperreports.repo.ReportResource;
import net.sf.jasperreports.repo.RepositoryContext;
import net.sf.jasperreports.repo.Resource;
import net.sf.jasperreports.repo.ResourceInfo;
import net.sf.jasperreports.repo.SimpleRepositoryContext;
import net.sf.jasperreports.repo.StandardResourceInfo;
import net.sf.jasperreports.repo.StreamRepositoryService;

import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ConcurrentMap;

/**
 * {@link StreamRepositoryService} nativo para o esquema {@code repo:} do JasperReports Server.
 *
 * <p>Intercepta URIs com prefixo {@code repo:} (case-insensitive), normaliza o caminho relativo
 * rejeitando qualquer tentativa de path traversal ({@code ..}), e busca em ordem determinística
 * nos diretórios locais espelhados ({@code <subreportDir>/repo}, {@code <subreportDir>},
 * {@code <baseDir>/repo}, {@code <baseDir>}), com fallback de extensões comuns e fallback por
 * basename em {@code <subreportDir>}.</p>
 *
 * <p>Suporta carregamento nativo de sub-relatórios compilados ({@code .jasper}), compilação
 * transparente sob demanda de {@code .jrxml} quando o {@code .jasper} ainda não existir,
 * imagens ({@code .png}, {@code .jpg}, {@code .svg}, etc.), templates de estilo ({@code .jrtx}),
 * bundles ({@code .properties}) e quaisquer outros recursos carregados via {@link PersistenceUtil}.</p>
 */
public final class RepoSchemeRepositoryService implements StreamRepositoryService {

    private static final String REPO_PREFIX = "repo:";
    private static final List<String> COMMON_EXTENSIONS = Collections.unmodifiableList(Arrays.asList(
            ".jasper",
            ".jrxml",
            ".png",
            ".jpg",
            ".jpeg",
            ".gif",
            ".svg",
            ".jrtx",
            ".properties"
    ));

    private static final byte[] JAVA_SERIALIZED_MAGIC = new byte[]{
            (byte) 0xAC, (byte) 0xED, (byte) 0x00, (byte) 0x05
    };

    private final JasperReportsContext jasperReportsContext;
    private final List<Path> searchRoots;
    private final List<Path> basenameFallbackRoots;
    private final ConcurrentMap<String, CachedReport> compiledJrxmlCache = new ConcurrentHashMap<>();

    private static final class CachedReport {
        final long lastModifiedMillis;
        final JasperReport report;

        CachedReport(long lastModifiedMillis, JasperReport report) {
            this.lastModifiedMillis = lastModifiedMillis;
            this.report = report;
        }
    }

    public RepoSchemeRepositoryService(
            JasperReportsContext jasperReportsContext,
            Path subreportDir,
            Path baseDir) {
        this.jasperReportsContext = jasperReportsContext;

        Set<Path> orderedRoots = new LinkedHashSet<>();
        Set<Path> orderedFallbacks = new LinkedHashSet<>();

        if (subreportDir != null) {
            Path normSub = subreportDir.toAbsolutePath().normalize();
            orderedRoots.add(normSub.resolve("repo").normalize());
            orderedRoots.add(normSub);
            orderedFallbacks.add(normSub);
        }
        if (baseDir != null) {
            Path normBase = baseDir.toAbsolutePath().normalize();
            orderedRoots.add(normBase.resolve("repo").normalize());
            orderedRoots.add(normBase);
            orderedFallbacks.add(normBase);
        }

        this.searchRoots = Collections.unmodifiableList(new ArrayList<>(orderedRoots));
        this.basenameFallbackRoots = Collections.unmodifiableList(new ArrayList<>(orderedFallbacks));
    }

    /** Retorna {@code true} se a URI começar com {@code repo:} (case-insensitive). */
    public static boolean isRepoUri(String uri) {
        if (uri == null) {
            return false;
        }
        String trimmed = uri.trim();
        return trimmed.length() > REPO_PREFIX.length()
                && trimmed.regionMatches(true, 0, REPO_PREFIX, 0, REPO_PREFIX.length());
    }

    /**
     * Normaliza o caminho relativo após {@code repo:}, rejeitando segmentos {@code ..},
     * caracteres nulos ou prefixos de drive (ex.: {@code C:}).
     */
    static List<String> normalizeRepoSegments(String uri) {
        if (!isRepoUri(uri)) {
            return null;
        }
        String raw = uri.trim().substring(REPO_PREFIX.length()).trim().replace('\\', '/');
        while (raw.startsWith("/")) {
            raw = raw.substring(1);
        }
        if (raw.isEmpty()) {
            return null;
        }
        String[] parts = raw.split("/");
        List<String> segments = new ArrayList<>(parts.length);
        for (String part : parts) {
            if (part.isEmpty() || ".".equals(part)) {
                continue;
            }
            if ("..".equals(part) || part.indexOf('\0') >= 0 || part.indexOf(':') >= 0) {
                return null;
            }
            segments.add(part);
        }
        return segments.isEmpty() ? null : segments;
    }

    /** Resolve a URI {@code repo:...} para um arquivo local existente, ou {@code null} se não encontrado. */
    Path resolveLocalFile(String uri, boolean preferCompiledReport) {
        List<String> segments = normalizeRepoSegments(uri);
        if (segments == null) {
            return null;
        }

        String relPath = String.join("/", segments);
        List<String> fullCandidates = buildCandidates(relPath, preferCompiledReport);

        // 1. Busca pela árvore relativa completa em cada raiz (<subreportDir>/repo, <subreportDir>, <baseDir>/repo, <baseDir>)
        for (Path root : searchRoots) {
            Path found = findFirstExisting(root, fullCandidates);
            if (found != null) {
                return found;
            }
        }

        // 2. Fallback por basename em <subreportDir> (e <baseDir>)
        String basename = segments.get(segments.size() - 1);
        List<String> baseCandidates = buildCandidates(basename, preferCompiledReport);
        for (Path fallbackRoot : basenameFallbackRoots) {
            Path found = findFirstExisting(fallbackRoot, baseCandidates);
            if (found != null) {
                return found;
            }
        }

        return null;
    }

    private static List<String> buildCandidates(String relPath, boolean preferCompiledReport) {
        Set<String> candidates = new LinkedHashSet<>();
        String lower = relPath.toLowerCase(Locale.ROOT);

        if (preferCompiledReport) {
            if (lower.endsWith(".jrxml")) {
                String stem = relPath.substring(0, relPath.length() - 6);
                candidates.add(stem + ".jasper");
                candidates.add(relPath);
            } else if (lower.endsWith(".jasper")) {
                String stem = relPath.substring(0, relPath.length() - 7);
                candidates.add(relPath);
                candidates.add(stem + ".jrxml");
            } else {
                candidates.add(relPath + ".jasper");
                candidates.add(relPath);
                candidates.add(relPath + ".jrxml");
            }
            return new ArrayList<>(candidates);
        }

        // Resolução geral: caminho exato primeiro
        candidates.add(relPath);
        if (lower.endsWith(".jrxml")) {
            String stem = relPath.substring(0, relPath.length() - 6);
            candidates.add(stem + ".jasper");
        }
        for (String ext : COMMON_EXTENSIONS) {
            if (!lower.endsWith(ext)) {
                candidates.add(relPath + ext);
            }
        }
        return new ArrayList<>(candidates);
    }

    private static Path findFirstExisting(Path root, List<String> relativeCandidates) {
        if (root == null || !Files.isDirectory(root)) {
            return null;
        }
        for (String candidate : relativeCandidates) {
            Path resolved = safeResolve(root, candidate);
            if (resolved != null && Files.isRegularFile(resolved)) {
                return resolved;
            }
        }
        return null;
    }

    private static Path safeResolve(Path root, String relativePosixPath) {
        Path current = root;
        for (String seg : relativePosixPath.split("/")) {
            if (seg.isEmpty() || ".".equals(seg)) {
                continue;
            }
            if ("..".equals(seg) || seg.indexOf('\0') >= 0 || seg.indexOf(':') >= 0) {
                return null;
            }
            current = current.resolve(seg);
        }
        Path normalized = current.normalize();
        if (!normalized.startsWith(root)) {
            return null;
        }
        return normalized;
    }

    private static boolean hasJavaSerializedMagic(Path file) {
        try (InputStream is = Files.newInputStream(file)) {
            byte[] header = new byte[4];
            int read = is.read(header);
            if (read < 4) {
                return false;
            }
            for (int i = 0; i < 4; i++) {
                if (header[i] != JAVA_SERIALIZED_MAGIC[i]) {
                    return false;
                }
            }
            return true;
        } catch (IOException e) {
            return false;
        }
    }

    private JasperReport loadOrCompileReport(Path target) throws JRException, IOException {
        String lowerName = target.getFileName().toString().toLowerCase(Locale.ROOT);
        if (hasJavaSerializedMagic(target) || lowerName.endsWith(".jasper")) {
            Object obj = JRLoader.loadObject(jasperReportsContext, target.toFile());
            if (obj instanceof JasperReport) {
                return (JasperReport) obj;
            }
            throw new JRException("O recurso '" + target + "' não contém um JasperReport válido.");
        }

        // Compila .jrxml sob demanda com cache por mtime
        long mtime = Files.getLastModifiedTime(target).toMillis();
        String cacheKey = target.toAbsolutePath().normalize().toString();
        CachedReport cached = compiledJrxmlCache.get(cacheKey);
        if (cached != null && cached.lastModifiedMillis == mtime) {
            return cached.report;
        }
        JasperDesign design = JRXmlLoader.load(target.toFile());
        JasperReport compiled = JasperCompileManager.getInstance(jasperReportsContext).compile(design);
        compiledJrxmlCache.put(cacheKey, new CachedReport(mtime, compiled));
        return compiled;
    }

    // ================================================================== StreamRepositoryService

    @Override
    public InputStream getInputStream(String uri) {
        return getInputStream(SimpleRepositoryContext.of(jasperReportsContext), uri);
    }

    @Override
    public InputStream getInputStream(RepositoryContext context, String uri) {
        if (!isRepoUri(uri)) {
            return null;
        }
        Path target = resolveLocalFile(uri, false);
        if (target == null) {
            return null;
        }
        try {
            return Files.newInputStream(target);
        } catch (IOException e) {
            throw new JRRuntimeException(e);
        }
    }

    @Override
    public OutputStream getOutputStream(String uri) {
        return null;
    }

    // ================================================================== RepositoryService

    @Override
    public Resource getResource(String uri) {
        if (!isRepoUri(uri)) {
            return null;
        }
        InputStream is = getInputStream(uri);
        if (is == null) {
            return null;
        }
        InputStreamResource resource = new InputStreamResource();
        resource.setName(uri);
        resource.setInputStream(is);
        return resource;
    }

    @Override
    public void saveResource(String uri, Resource resource) {
        // Repositório local de leitura somente.
    }

    @Override
    public <K extends Resource> K getResource(String uri, Class<K> resourceType) {
        return getResource(SimpleRepositoryContext.of(jasperReportsContext), uri, resourceType);
    }

    @Override
    public <K extends Resource> K getResource(
            RepositoryContext context,
            String uri,
            Class<K> resourceType) {
        if (!isRepoUri(uri) || resourceType == null) {
            return null;
        }

        if (ReportResource.class.equals(resourceType)) {
            Path target = resolveLocalFile(uri, true);
            if (target == null) {
                return null;
            }
            try {
                JasperReport report = loadOrCompileReport(target);
                ReportResource resource = new ReportResource();
                resource.setName(uri);
                resource.setReport(report);
                return resourceType.cast(resource);
            } catch (JRException | IOException e) {
                throw new JRRuntimeException(e);
            }
        }

        if (InputStreamResource.class.equals(resourceType)) {
            InputStream is = getInputStream(context, uri);
            if (is == null) {
                return null;
            }
            InputStreamResource resource = new InputStreamResource();
            resource.setName(uri);
            resource.setInputStream(is);
            return resourceType.cast(resource);
        }

        Path target = resolveLocalFile(uri, false);
        if (target == null) {
            return null;
        }

        PersistenceService persistenceService = PersistenceUtil.getInstance(jasperReportsContext)
                .getService(FileRepositoryService.class, resourceType);
        if (persistenceService != null) {
            RepositoryContext effectiveCtx = context != null
                    ? context
                    : SimpleRepositoryContext.of(jasperReportsContext);
            Resource loaded = persistenceService.load(effectiveCtx, uri, this);
            if (loaded != null && resourceType.isInstance(loaded)) {
                return resourceType.cast(loaded);
            }
        }
        return null;
    }

    @Override
    public ResourceInfo getResourceInfo(RepositoryContext context, String uri) {
        if (!isRepoUri(uri)) {
            return null;
        }
        Path target = resolveLocalFile(uri, false);
        if (target == null) {
            return null;
        }
        try {
            return StandardResourceInfo.from(target.toRealPath());
        } catch (IOException e) {
            return null;
        }
    }
}
