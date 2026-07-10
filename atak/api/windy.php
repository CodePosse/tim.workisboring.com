<?php
declare(strict_types=1);

header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: public, max-age=240');

const WINDY_API = 'https://api.windy.com/webcams/api/v3/webcams';
const CACHE_FILE = '/tmp/socal-tak-windy.json';
const CACHE_SECONDS = 240;

$regions = [
    ['Los Angeles', 34.0522, -118.2437, 150],
    ['Orange County', 33.7175, -117.8311, 100],
    ['San Diego', 32.7157, -117.1611, 120],
    ['Ventura', 34.2805, -119.2945, 100],
    ['Santa Barbara', 34.4208, -119.6982, 100],
    ['Palm Springs', 33.8303, -116.5453, 100],
    ['Big Bear', 34.2439, -116.9114, 100],
    ['Lake Arrowhead', 34.2483, -117.1892, 80],
];

function failResponse(string $message, int $status = 500): never
{
    http_response_code($status);
    echo json_encode([
        'error' => true,
        'message' => $message,
        'cameras' => [],
    ], JSON_UNESCAPED_SLASHES | JSON_PRETTY_PRINT);
    exit;
}

function loadEnvironment(string $path): void
{
    if (!is_readable($path)) {
        return;
    }

    $lines = file($path, FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES);

    foreach ($lines as $line) {
        $line = trim($line);

        if ($line === '' || str_starts_with($line, '#')) {
            continue;
        }

        $line = preg_replace('/^export\s+/', '', $line);

        if (!str_contains($line, '=')) {
            continue;
        }

        [$name, $value] = explode('=', $line, 2);
        $name = trim($name);
        $value = trim($value, " \t\n\r\0\x0B\"'");

        if ($name !== '') {
            putenv($name . '=' . $value);
            $_ENV[$name] = $value;
        }
    }
}

function apiRequest(string $url, string $apiKey): array
{
    $curl = curl_init($url);

    curl_setopt_array($curl, [
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_CONNECTTIMEOUT => 10,
        CURLOPT_TIMEOUT => 30,
        CURLOPT_HTTPHEADER => [
            'Accept: application/json',
            'x-windy-api-key: ' . $apiKey,
            'User-Agent: SoCal-TAK/1.0',
        ],
    ]);

    $body = curl_exec($curl);
    $status = (int) curl_getinfo($curl, CURLINFO_HTTP_CODE);
    $error = curl_error($curl);

    curl_close($curl);

    if ($body === false || $error !== '') {
        throw new RuntimeException('Windy request failed: ' . $error);
    }

    if ($status < 200 || $status >= 300) {
        throw new RuntimeException('Windy returned HTTP ' . $status);
    }

    $decoded = json_decode($body, true);

    if (!is_array($decoded)) {
        throw new RuntimeException('Windy returned invalid JSON.');
    }

    return $decoded;
}

function pick(array $data, array $keys, mixed $default = ''): mixed
{
    foreach ($keys as $key) {
        if (array_key_exists($key, $data) && $data[$key] !== null && $data[$key] !== '') {
            return $data[$key];
        }
    }

    return $default;
}

function firstUrl(mixed $value): string
{
    if (is_string($value)) {
        return $value;
    }

    if (!is_array($value)) {
        return '';
    }

    foreach (['url', 'preview', 'thumbnail', 'full', 'day', 'month', 'lifetime'] as $key) {
        if (!empty($value[$key]) && is_string($value[$key])) {
            return $value[$key];
        }
    }

    return '';
}

function inSouthernCalifornia(float $lat, float $lon): bool
{
    return $lat >= 32.3 && $lat <= 36.8 && $lon >= -121.0 && $lon <= -114.0;
}

if (
    is_readable(CACHE_FILE) &&
    filemtime(CACHE_FILE) !== false &&
    filemtime(CACHE_FILE) > time() - CACHE_SECONDS
) {
    readfile(CACHE_FILE);
    exit;
}

loadEnvironment('/etc/socal-tak.env');

$apiKey = getenv('WINDY_API_KEY');

if (!$apiKey) {
    failResponse('WINDY_API_KEY is not configured.');
}

$cameras = [];
$errors = [];

foreach ($regions as [$regionName, $latitude, $longitude, $radius]) {
    $query = http_build_query([
        'limit' => 50,
        'nearby' => sprintf('%s,%s,%s', $latitude, $longitude, $radius),
        'include' => 'images,location,player,urls,categories',
    ]);

    try {
        $payload = apiRequest(WINDY_API . '?' . $query, $apiKey);
    } catch (Throwable $error) {
        $errors[] = $regionName . ': ' . $error->getMessage();
        continue;
    }

    foreach (($payload['webcams'] ?? []) as $camera) {
        if (!is_array($camera)) {
            continue;
        }

        $id = (string) pick($camera, ['webcamId', 'id']);

        if ($id === '') {
            continue;
        }

        $location = is_array($camera['location'] ?? null)
            ? $camera['location']
            : [];

        $lat = (float) pick($location, ['latitude', 'lat'], 0);
        $lon = (float) pick($location, ['longitude', 'lon', 'lng'], 0);

        if (!inSouthernCalifornia($lat, $lon)) {
            continue;
        }

        $images = is_array($camera['images'] ?? null)
            ? $camera['images']
            : [];

        $current = is_array($images['current'] ?? null)
            ? $images['current']
            : [];

        $urls = is_array($camera['urls'] ?? null)
            ? $camera['urls']
            : [];

        $player = is_array($camera['player'] ?? null)
            ? $camera['player']
            : [];

        $thumbnail =
            firstUrl($current['thumbnail'] ?? '') ?:
            firstUrl($current['preview'] ?? '') ?:
            firstUrl($current['full'] ?? '');

        $imageUrl =
            firstUrl($current['full'] ?? '') ?:
            firstUrl($current['preview'] ?? '') ?:
            $thumbnail;

        $webcamPage =
            firstUrl($urls['detail'] ?? '') ?:
            firstUrl($urls['web'] ?? '') ?:
            firstUrl($player['day'] ?? '') ?:
            'https://www.windy.com/webcams';

        $cameras[$id] = [
            'id' => 'windy-' . $id,
            'name' => (string) pick($camera, ['title', 'name'], 'Windy Webcam'),
            'source' => 'Windy Webcams',
            'category' => '🌎 Tourist Webcam',
            'lat' => $lat,
            'lon' => $lon,
            'county' => '',
            'heading' => '',
            'thumbnail' => $thumbnail ?: $imageUrl,
            'url' => $webcamPage,
            'region' => $regionName,
            'attribution' => 'Webcams provided by Windy.com',
        ];
    }
}

$result = [
    'source_key' => 'windy',
    'title' => 'Windy Southern California Webcams',
    'generated_at' => time(),
    'count' => count($cameras),
    'errors' => $errors,
    'cameras' => array_values($cameras),
];

$json = json_encode(
    $result,
    JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE | JSON_PRETTY_PRINT
);

if ($json === false) {
    failResponse('Unable to encode Windy response.');
}

/*
 * Do not replace the cache with an empty response if a previous
 * non-empty cache exists.
 */
if (count($cameras) === 0 && is_readable(CACHE_FILE)) {
    readfile(CACHE_FILE);
    exit;
}

file_put_contents(CACHE_FILE, $json, LOCK_EX);
echo $json;
